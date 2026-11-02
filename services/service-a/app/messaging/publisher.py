import json
import logging
from datetime import UTC, datetime

import aio_pika
from aio_pika import DeliveryMode, ExchangeType
from aio_pika.abc import (
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustExchange,
)

from app.config import settings

logger = logging.getLogger("service-a.publisher")


class MessagePublisher:
    """Manages a long-lived AMQP connection and publishes persistent messages."""

    def __init__(self, rabbitmq_url: str):
        self.rabbitmq_url = rabbitmq_url
        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractRobustChannel | None = None
        self.exchange: AbstractRobustExchange | None = None

    async def connect(self) -> None:
        """Establishes connection, opens channel, and ensures primary exchange exists."""
        logger.info("Connecting to RabbitMQ at %s...", self.rabbitmq_url)
        self.connection = await aio_pika.connect_robust(self.rabbitmq_url)
        self.channel = await self.connection.channel()

        # Idempotently declare the primary exchange to avoid startup race conditions
        self.exchange = await self.channel.declare_exchange(
            name=settings.rabbitmq_exchange_name,
            type=ExchangeType.DIRECT,
            durable=True,
        )
        logger.info("Publisher ready. Bound to exchange '%s'", settings.rabbitmq_exchange_name)

    async def close(self) -> None:
        """Closes AMQP channel and connection gracefully."""
        if self.channel and not self.channel.is_closed:
            await self.channel.close()
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        logger.info("Publisher connection closed.")

    async def publish_task(
        self,
        request_id: str,
        latency_ms: int,
        failure_rate_pct: float,
    ) -> dict[str, str | int | float]:
        """Packages task envelope and publishes with DeliveryMode.PERSISTENT."""
        if not self.exchange:
            raise RuntimeError("Publisher is not connected to RabbitMQ. Call connect() first.")

        payload = {
            "request_id": request_id,
            "latency_ms": latency_ms,
            "failure_rate_pct": failure_rate_pct,
            "enqueued_at": datetime.now(UTC).isoformat(),
            "origin": settings.service_name,
        }

        body = json.dumps(payload).encode("utf-8")

        message = aio_pika.Message(
            body=body,
            delivery_mode=DeliveryMode.PERSISTENT,  # Writes to disk for durability
            content_type="application/json",
            correlation_id=request_id,
            message_id=request_id,
            timestamp=datetime.now(UTC),
        )

        await self.exchange.publish(
            message=message,
            routing_key=settings.rabbitmq_routing_key,
        )

        logger.info(
            "Published task to '%s' with key '%s': id=%s",
            settings.rabbitmq_exchange_name,
            settings.rabbitmq_routing_key,
            request_id,
        )
        return payload

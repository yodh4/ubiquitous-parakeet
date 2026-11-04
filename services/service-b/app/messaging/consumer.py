import asyncio
import json
import logging
import random
import socket

import aio_pika
from aio_pika import connect_robust
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
    AbstractRobustQueue,
)

from app.config import settings
from app.messaging.idempotency import IdempotencyStore
from app.messaging.topology import setup_topology

logger = logging.getLogger("service-b.consumer")
HOSTNAME = socket.gethostname()


class TaskConsumer:
    """Consumes tasks from RabbitMQ with controlled concurrency and manual acknowledgments."""

    def __init__(self, rabbitmq_url: str, prefetch_count: int = 5):
        self.rabbitmq_url = rabbitmq_url
        self.prefetch_count = prefetch_count

        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractRobustChannel | None = None
        self.queue: AbstractRobustQueue | None = None
        self.consumer_tag: str | None = None

        self.is_running: bool = False
        self.total_received: int = 0
        self.total_completed: int = 0
        self.total_failed: int = 0
        self.total_duplicates_skipped: int = 0
        self.active_in_flight: int = 0
        self.last_processed_id: str | None = None
        self.last_error: str | None = None

        self.idempotency_store = IdempotencyStore(
            default_ttl_seconds=settings.idempotency_ttl_seconds,
            max_capacity=settings.idempotency_max_capacity,
        )

        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Connects to RabbitMQ, sets prefetch backpressure, and begins consuming."""
        logger.info("TaskConsumer connecting to RabbitMQ at %s...", self.rabbitmq_url)
        self.connection = await connect_robust(self.rabbitmq_url)
        self.channel = await self.connection.channel()

        # Step 1: Enforce Backpressure (FR-3.2)
        await self.channel.set_qos(prefetch_count=self.prefetch_count)
        logger.info("Enforced consumer prefetch_count=%d", self.prefetch_count)

        # Step 2: Ensure AMQP Topology (Exchanges, Queues, DLX, DLQ) exists
        _, self.queue, _, _ = await setup_topology(self.channel)

        # Step 3: Register message handler
        self.is_running = True
        self.consumer_tag = await self.queue.consume(self._handle_message)
        logger.info("TaskConsumer started listening on '%s'", self.queue.name)

    async def stop(self) -> None:
        """Stops consuming and cleanly releases channel and connection."""
        self.is_running = False
        if self.queue and self.consumer_tag:
            try:
                await self.queue.cancel(self.consumer_tag)
            except (aio_pika.exceptions.AMQPException, OSError) as exc:
                logger.warning("Error cancelling consumer tag: %s", exc)

        if self.channel and not self.channel.is_closed:
            await self.channel.close()
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        logger.info("TaskConsumer stopped cleanly.")

    async def _handle_message(self, message: AbstractIncomingMessage) -> None:
        """Dispatches an incoming message to the workload simulator and handles ACK/NACK."""
        async with self._lock:
            self.total_received += 1
            self.active_in_flight += 1

        request_id = "unknown"
        try:
            # Parse payload envelope
            data = json.loads(message.body.decode("utf-8"))
            request_id = data.get("request_id", str(message.message_id or "unknown"))
            latency_ms = int(data.get("latency_ms", 0))
            failure_rate_pct = float(data.get("failure_rate_pct", 0.0))

            logger.info(
                "Processing message id=%s (latency_ms=%d, failure_rate=%.1f%%, in_flight=%d)",
                request_id,
                latency_ms,
                failure_rate_pct,
                self.active_in_flight,
            )

            # Step 1: Atomic Idempotency Check & In-Flight Lease Acquisition (FR-3.3)
            acquired = await self.idempotency_store.check_and_acquire(request_id)
            if not acquired:
                logger.warning(
                    "Duplicate message id=%s detected (in-flight or completed). Suppressing work and ACK-ing.",
                    request_id,
                )
                await message.ack()
                async with self._lock:
                    self.total_duplicates_skipped += 1
                    self.active_in_flight -= 1
                return

            try:
                # Step 2: Simulate artificial latency if specified
                if latency_ms > 0:
                    await asyncio.sleep(latency_ms / 1000.0)

                # Step 3: Simulate probabilistic failure if specified
                if failure_rate_pct > 0:
                    roll = random.uniform(0.0, 100.0)
                    if roll < failure_rate_pct:
                        raise RuntimeError(
                            f"Simulated consumer failure (roll={roll:.2f} < threshold={failure_rate_pct:.2f})"
                        )

                # Step 4: Mark COMPLETED in deduplication store and send manual ACK
                await self.idempotency_store.mark_completed(request_id)
                await message.ack()

                async with self._lock:
                    self.total_completed += 1
                    self.last_processed_id = request_id
                    self.active_in_flight -= 1

                logger.info("Successfully completed and ACKed task id=%s", request_id)

            except Exception:
                # Release in-flight lease on failure so redelivery or DLQ tracking is unblocked
                await self.idempotency_store.release_in_flight(request_id)
                raise

        except Exception as exc:  # noqa: BLE001 - Worker catch-all to guarantee unhandled task crashes are NACKed to DLQ rather than dropped
            # Unhandled or simulated error -> Send manual NACK without requeue
            # RabbitMQ will automatically route this poison message to sandbox.dlx -> sandbox.tasks.dlq
            logger.warning("Task id=%s failed: %s. Rejecting with requeue=False (DLQ)", request_id, exc)
            try:
                await message.nack(requeue=False)
            except (aio_pika.exceptions.AMQPException, OSError) as nack_exc:
                logger.error("Failed to NACK message id=%s: %s", request_id, nack_exc)

            async with self._lock:
                self.total_failed += 1
                self.last_error = str(exc)
                self.active_in_flight -= 1

    def get_stats(self) -> dict:
        """Returns live telemetry snapshot of the consumer."""
        return {
            "service": settings.service_name,
            "is_running": self.is_running,
            "prefetch_count": self.prefetch_count,
            "total_received": self.total_received,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_duplicates_skipped": self.total_duplicates_skipped,
            "active_in_flight": self.active_in_flight,
            "last_processed_id": self.last_processed_id,
            "last_error": self.last_error,
        }

    async def get_dlq_message_count(self) -> int:
        """Queries RabbitMQ directly over AMQP wire for the current count of quarantined poison messages."""
        if not self.channel or self.channel.is_closed:
            return 0
        try:
            # Bypass RobustChannel local cache to query live broker state via passive queue declare
            res = await self.channel.channel.queue_declare(settings.rabbitmq_dlq_name, passive=True)
            return int(res.message_count)
        except (aio_pika.exceptions.AMQPException, OSError) as exc:
            logger.warning("Could not query DLQ message count: %s", exc)
            return 0

    async def purge_dlq(self) -> int:
        """Purges all messages from the Dead Letter Queue (useful for test resets)."""
        if not self.channel or self.channel.is_closed:
            return 0
        try:
            res = await self.channel.channel.queue_purge(settings.rabbitmq_dlq_name)
            return int(res.message_count)
        except (aio_pika.exceptions.AMQPException, OSError) as exc:
            logger.warning("Could not purge DLQ: %s", exc)
            return 0

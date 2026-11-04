import asyncio
import logging
import random
import socket
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import aio_pika
from fastapi import FastAPI, HTTPException, Request, status

from app.config import settings
from app.messaging.consumer import TaskConsumer
from app.schemas import (
    ConsumerStatsResponse,
    DLQStatusResponse,
    HealthResponse,
    WorkRequest,
    WorkResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup shared background RabbitMQ TaskConsumer (Milestone 3)
    consumer = TaskConsumer(
        rabbitmq_url=settings.rabbitmq_url,
        prefetch_count=settings.rabbitmq_prefetch_count,
    )
    app.state.consumer = consumer

    try:
        await consumer.start()
    except (aio_pika.exceptions.AMQPException, OSError) as exc:
        logger.warning("Could not connect consumer to RabbitMQ on startup: %s. Continuing in degraded mode.", exc)

    yield
    # Clean up consumer on shutdown
    if getattr(app.state, "consumer", None):
        await app.state.consumer.stop()


app = FastAPI(
    title="Service B (Worker / Consumer)",
    description="Receives tasks, executes simulated work or simulated failures.",
    version="0.2.0",
    lifespan=lifespan,
)

# Initialize defaults on app.state for testing and non-lifespan runs
app.state.consumer = TaskConsumer(
    rabbitmq_url=settings.rabbitmq_url,
    prefetch_count=settings.rabbitmq_prefetch_count,
)

HOSTNAME = socket.gethostname()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(service=settings.service_name)


@app.get("/consumer/stats", response_model=ConsumerStatsResponse)
async def get_consumer_stats(request: Request):
    consumer: TaskConsumer = request.app.state.consumer
    stats = consumer.get_stats()
    stats["dlq_message_count"] = await consumer.get_dlq_message_count()
    return ConsumerStatsResponse(**stats)


@app.get("/consumer/dlq", response_model=DLQStatusResponse)
async def get_dlq_status(request: Request):
    consumer: TaskConsumer = request.app.state.consumer
    count = await consumer.get_dlq_message_count()
    return DLQStatusResponse(
        queue=settings.rabbitmq_dlq_name,
        exchange=settings.rabbitmq_dlx_name,
        message_count=count,
    )


@app.post("/consumer/dlq/purge")
async def purge_dlq_messages(request: Request):
    consumer: TaskConsumer = request.app.state.consumer
    purged_count = await consumer.purge_dlq()
    return {
        "status": "purged",
        "queue": settings.rabbitmq_dlq_name,
        "purged_count": purged_count,
    }


@app.post("/consumer/reset")
async def reset_consumer_state(request: Request):
    consumer: TaskConsumer = request.app.state.consumer
    await consumer.reset()
    return {"status": "reset", "service": settings.service_name}


@app.post("/work", response_model=WorkResponse, status_code=status.HTTP_200_OK)
async def perform_work(payload: WorkRequest):
    logger.info(
        "Received work request: id=%s latency_ms=%d failure_rate_pct=%.1f%%",
        payload.request_id,
        payload.latency_ms,
        payload.failure_rate_pct,
    )

    # 1. Simulate artificial latency if specified
    if payload.latency_ms > 0:
        await asyncio.sleep(payload.latency_ms / 1000.0)

    # 2. Simulate probabilistic failure if specified
    if payload.failure_rate_pct > 0:
        roll = random.uniform(0.0, 100.0)
        if roll < payload.failure_rate_pct:
            logger.warning(
                "Injected simulated failure for request id=%s (roll=%.2f < threshold=%.2f)",
                payload.request_id,
                roll,
                payload.failure_rate_pct,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "SimulatedFailure",
                    "message": "Simulated failure in Service B",
                    "request_id": payload.request_id,
                    "simulated_latency_ms": payload.latency_ms,
                    "hostname": HOSTNAME,
                },
            )

    logger.info("Successfully completed work for request id=%s", payload.request_id)
    return WorkResponse(
        request_id=payload.request_id,
        status="completed",
        service=settings.service_name,
        hostname=HOSTNAME,
        simulated_latency_ms=payload.latency_ms,
        completed_at=datetime.now(UTC),
    )

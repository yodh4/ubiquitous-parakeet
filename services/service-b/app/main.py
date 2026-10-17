import asyncio
import logging
import random
import socket
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, status

from app.config import settings
from app.schemas import HealthResponse, WorkRequest, WorkResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(settings.service_name)

app = FastAPI(
    title="Service B (Worker / Consumer)",
    description="Receives tasks, executes simulated work or simulated failures.",
    version="0.1.0",
)

HOSTNAME = socket.gethostname()


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(service=settings.service_name)


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

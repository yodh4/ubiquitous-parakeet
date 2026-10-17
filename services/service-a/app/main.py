import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.schemas import HealthResponse, TriggerRequest, TriggerResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup shared httpx.AsyncClient with connection pooling
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_seconds)
    )
    yield
    # Clean up client on shutdown
    await app.state.http_client.aclose()


app = FastAPI(
    title="Service A (Ingress / Producer)",
    description="Accepts incoming requests and coordinates downstream execution.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(service=settings.service_name)


@app.post(
    "/trigger",
    response_model=TriggerResponse,
    responses={
        200: {"model": TriggerResponse, "description": "Successful execution"},
        502: {"model": TriggerResponse, "description": "Downstream Service B returned an error"},
        503: {"model": TriggerResponse, "description": "Service B connection failure"},
        504: {"model": TriggerResponse, "description": "Service B request timed out"},
    },
)
async def trigger_work(payload: TriggerRequest, request: Request):
    request_id = str(uuid.uuid4())
    logger.info(
        "Initiating trigger request: id=%s target_latency=%d target_failure_rate=%.1f%%",
        request_id,
        payload.latency_ms,
        payload.failure_rate_pct,
    )

    client: httpx.AsyncClient = request.app.state.http_client
    url = f"{settings.service_b_url}/work"
    downstream_payload = {
        "request_id": request_id,
        "latency_ms": payload.latency_ms,
        "failure_rate_pct": payload.failure_rate_pct,
    }

    start_time = time.perf_counter()

    try:
        response = await client.post(url, json=downstream_payload)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        if response.status_code == status.HTTP_200_OK:
            logger.info("Request id=%s completed successfully in %.2fms", request_id, duration_ms)
            return TriggerResponse(
                request_id=request_id,
                status="success",
                round_trip_duration_ms=round(duration_ms, 2),
                service_a_timestamp=datetime.now(UTC),
                downstream=response.json(),
            )

        # Downstream error (e.g. 500 from simulated failure)
        logger.warning(
            "Downstream Service B returned status %d for request id=%s (took %.2fms)",
            response.status_code,
            request_id,
            duration_ms,
        )
        try:
            downstream_error_data = response.json()
        except ValueError:
            downstream_error_data = {"raw": response.text}

        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=TriggerResponse(
                request_id=request_id,
                status="downstream_error",
                round_trip_duration_ms=round(duration_ms, 2),
                service_a_timestamp=datetime.now(UTC),
                error=downstream_error_data,
            ).model_dump(mode="json"),
        )

    except httpx.TimeoutException as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.error("Request id=%s timed out after %.2fms: %s", request_id, duration_ms, exc)
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=TriggerResponse(
                request_id=request_id,
                status="timeout",
                round_trip_duration_ms=round(duration_ms, 2),
                service_a_timestamp=datetime.now(UTC),
                error="Downstream Service B timed out",
            ).model_dump(mode="json"),
        )

    except httpx.ConnectError as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.error("Failed to connect to Service B for request id=%s: %s", request_id, exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=TriggerResponse(
                request_id=request_id,
                status="connection_error",
                round_trip_duration_ms=round(duration_ms, 2),
                service_a_timestamp=datetime.now(UTC),
                error="Could not connect to downstream Service B",
            ).model_dump(mode="json"),
        )

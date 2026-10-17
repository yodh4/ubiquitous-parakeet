import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenException,
    RetryPolicy,
    execute_with_retry,
)
from app.schemas import (
    CircuitBreakerResetResponse,
    CircuitBreakerStatusResponse,
    HealthResponse,
    ResilienceMetadata,
    TriggerRequest,
    TriggerResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup shared httpx.AsyncClient with connection pooling
    app.state.http_client = httpx.AsyncClient()
    # Setup shared CircuitBreaker state machine
    app.state.circuit_breaker = CircuitBreaker(
        failure_threshold=settings.cb_failure_threshold,
        recovery_timeout_seconds=settings.cb_recovery_timeout_seconds,
    )
    yield
    # Clean up client on shutdown
    await app.state.http_client.aclose()


app = FastAPI(
    title="Service A (Ingress / Producer)",
    description="Accepts incoming requests, applies resilience patterns, and coordinates downstream execution.",
    version="0.2.0",
    lifespan=lifespan,
)

# Initialize defaults on app.state for testing and non-lifespan runs
app.state.circuit_breaker = CircuitBreaker(
    failure_threshold=settings.cb_failure_threshold,
    recovery_timeout_seconds=settings.cb_recovery_timeout_seconds,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(service=settings.service_name)


@app.get("/circuit-breaker", response_model=CircuitBreakerStatusResponse)
async def get_circuit_breaker_status(request: Request):
    cb: CircuitBreaker = request.app.state.circuit_breaker
    return CircuitBreakerStatusResponse(**cb.get_status())


@app.post("/circuit-breaker/reset", response_model=CircuitBreakerResetResponse)
async def reset_circuit_breaker(request: Request):
    cb: CircuitBreaker = request.app.state.circuit_breaker
    await cb.reset()
    return CircuitBreakerResetResponse(circuit_breaker=CircuitBreakerStatusResponse(**cb.get_status()))


@app.post(
    "/trigger",
    response_model=TriggerResponse,
    responses={
        200: {"model": TriggerResponse, "description": "Successful execution or graceful degraded fallback"},
        502: {"model": TriggerResponse, "description": "Downstream Service B returned an error"},
        503: {"model": TriggerResponse, "description": "Service B connection failure"},
        504: {"model": TriggerResponse, "description": "Service B request timed out"},
    },
)
async def trigger_work(payload: TriggerRequest, request: Request):
    request_id = str(uuid.uuid4())
    cb: CircuitBreaker = request.app.state.circuit_breaker
    client: httpx.AsyncClient = request.app.state.http_client

    # Resolve per-request configuration overrides
    timeout_seconds = (
        payload.timeout_ms / 1000.0 if payload.timeout_ms is not None else settings.request_timeout_seconds
    )
    max_retries = (
        payload.max_retries
        if payload.max_retries is not None
        else (settings.default_max_retries if payload.use_retry else 0)
    )

    start_time = time.perf_counter()

    # Step 1: Circuit Breaker Gate (FR-2.3)
    if payload.use_circuit_breaker:
        try:
            await cb.acquire_permission()
        except CircuitBreakerOpenException as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning("Circuit Breaker OPEN for request id=%s. Fast-failing in %.2fms", request_id, duration_ms)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=TriggerResponse(
                    request_id=request_id,
                    status="degraded_fallback",
                    round_trip_duration_ms=round(duration_ms, 2),
                    service_a_timestamp=datetime.now(UTC),
                    error={
                        "message": "Downstream service is currently unavailable. Circuit breaker is OPEN.",
                        "reason": exc.last_failure_reason,
                        "cooldown_remaining_seconds": exc.cooldown_remaining_seconds,
                    },
                    resilience=ResilienceMetadata(
                        circuit_breaker_state=cb.state.value,
                        attempts=0,
                        retry_delays_ms=[],
                        timeout_enforced_ms=timeout_seconds * 1000.0,
                        circuit_breaker_tripped=True,
                        cooldown_remaining_seconds=exc.cooldown_remaining_seconds,
                    ),
                ).model_dump(mode="json"),
            )

    # Step 2: Prepare Per-Attempt Timeout (FR-2.1) & Operation
    downstream_url = f"{settings.service_b_url}/work"
    downstream_payload = {
        "request_id": request_id,
        "latency_ms": payload.latency_ms,
        "failure_rate_pct": payload.failure_rate_pct,
    }
    per_attempt_timeout = httpx.Timeout(timeout_seconds, connect=1.0)

    async def single_call() -> httpx.Response:
        return await asyncio.wait_for(
            client.post(downstream_url, json=downstream_payload, timeout=per_attempt_timeout),
            timeout=timeout_seconds,
        )

    # Step 3: Execute through Retry Coordinator with Exponential Backoff & Full Jitter (FR-2.2)
    retry_policy = RetryPolicy(
        max_retries=max_retries,
        base_delay_ms=settings.default_base_delay_ms,
        max_delay_ms=settings.default_max_delay_ms,
        jitter=payload.use_jitter,
    )

    retry_result = await execute_with_retry(single_call, retry_policy, request_id=request_id)
    duration_ms = (time.perf_counter() - start_time) * 1000.0

    resilience_meta = ResilienceMetadata(
        circuit_breaker_state=cb.state.value,
        attempts=retry_result.attempts,
        retry_delays_ms=retry_result.retry_delays_ms,
        timeout_enforced_ms=timeout_seconds * 1000.0,
        circuit_breaker_tripped=False,
    )

    # Step 4: Handle Successful Result
    if retry_result.response is not None and retry_result.response.status_code == status.HTTP_200_OK:
        if payload.use_circuit_breaker:
            await cb.record_success()

        return TriggerResponse(
            request_id=request_id,
            status="success",
            round_trip_duration_ms=round(duration_ms, 2),
            service_a_timestamp=datetime.now(UTC),
            downstream=retry_result.response.json(),
            resilience=resilience_meta,
        )

    # Step 5: Handle Failures and Record to Circuit Breaker
    failure_reason = "Unknown downstream error"

    if isinstance(retry_result.last_exception, (httpx.TimeoutException, TimeoutError)):
        failure_reason = f"Downstream timed out after {timeout_seconds}s per attempt"
        if payload.use_circuit_breaker:
            await cb.record_failure(reason=failure_reason)

        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=TriggerResponse(
                request_id=request_id,
                status="timeout",
                round_trip_duration_ms=round(duration_ms, 2),
                service_a_timestamp=datetime.now(UTC),
                error=failure_reason,
                resilience=resilience_meta,
            ).model_dump(mode="json"),
        )

    if isinstance(retry_result.last_exception, httpx.ConnectError):
        failure_reason = "Connection refused / unable to reach Service B"
        if payload.use_circuit_breaker:
            await cb.record_failure(reason=failure_reason)

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=TriggerResponse(
                request_id=request_id,
                status="connection_error",
                round_trip_duration_ms=round(duration_ms, 2),
                service_a_timestamp=datetime.now(UTC),
                error=failure_reason,
                resilience=resilience_meta,
            ).model_dump(mode="json"),
        )

    # Downstream error response (e.g. 500 from simulated failure)
    downstream_data = None
    if retry_result.response is not None:
        failure_reason = f"Service B returned HTTP {retry_result.response.status_code}"
        try:
            downstream_data = retry_result.response.json()
        except ValueError:
            downstream_data = {"raw": retry_result.response.text}

    if payload.use_circuit_breaker:
        await cb.record_failure(reason=failure_reason)

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content=TriggerResponse(
            request_id=request_id,
            status="downstream_error",
            round_trip_duration_ms=round(duration_ms, 2),
            service_a_timestamp=datetime.now(UTC),
            error=downstream_data or failure_reason,
            resilience=resilience_meta,
        ).model_dump(mode="json"),
    )

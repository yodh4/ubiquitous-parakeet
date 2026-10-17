import asyncio
import importlib.util
import sys
import time
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

ROOT_DIR = Path(__file__).resolve().parent.parent


def load_app(service_name: str):
    app_path = ROOT_DIR / "services" / service_name / "app" / "main.py"
    module_name = f"{service_name.replace('-', '_')}_app_main_m2"

    service_dir = str(ROOT_DIR / "services" / service_name)
    if service_dir in sys.path:
        sys.path.remove(service_dir)
    sys.path.insert(0, service_dir)

    for mod in list(sys.modules.keys()):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    spec = importlib.util.spec_from_file_location(module_name, str(app_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.app


service_b_app = load_app("service-b")
service_a_app = load_app("service-a")

from app.resilience.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitBreakerOpenException,
)
from app.resilience.retry import RetryPolicy, execute_with_retry

# -----------------------------------------------------------------------------
# 1. Unit Tests: CircuitBreaker State Machine
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_initial_state():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=1.0)
    assert cb.state == BreakerState.CLOSED
    assert cb.failure_count == 0
    # Should not raise
    await cb.acquire_permission()


@pytest.mark.asyncio
async def test_circuit_breaker_trips_to_open_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=0.2)
    
    await cb.record_failure("error 1")
    assert cb.state == BreakerState.CLOSED
    assert cb.failure_count == 1

    await cb.record_failure("error 2")
    assert cb.state == BreakerState.CLOSED
    assert cb.failure_count == 2

    await cb.record_failure("error 3")
    assert cb.state == BreakerState.OPEN
    assert cb.failure_count == 3

    # Fast-fail when OPEN
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        await cb.acquire_permission()
    assert "Circuit Breaker is OPEN" in str(exc_info.value)
    assert exc_info.value.cooldown_remaining_seconds > 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.1)
    await cb.record_failure("err 1")
    await cb.record_failure("err 2")
    assert cb.state == BreakerState.OPEN

    # Wait for cooldown to expire
    await asyncio.sleep(0.12)

    # Permission granted as canary probe (HALF_OPEN)
    await cb.acquire_permission()
    assert cb.state == BreakerState.HALF_OPEN

    # Succeeded canary probe heals circuit back to CLOSED
    await cb.record_success()
    assert cb.state == BreakerState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_failure_retrips():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.1)
    await cb.record_failure("err 1")
    await cb.record_failure("err 2")
    assert cb.state == BreakerState.OPEN

    await asyncio.sleep(0.12)
    await cb.acquire_permission()
    assert cb.state == BreakerState.HALF_OPEN

    # Failed canary probe immediately re-trips back to OPEN
    await cb.record_failure("canary failed")
    assert cb.state == BreakerState.OPEN


# -----------------------------------------------------------------------------
# 2. Unit Tests: Retry with Exponential Backoff & Jitter
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_policy_exponential_backoff_delays():
    policy = RetryPolicy(max_retries=3, base_delay_ms=10.0, max_delay_ms=80.0, jitter=False)
    assert policy.calculate_delay_ms(0) == 10.0
    assert policy.calculate_delay_ms(1) == 20.0
    assert policy.calculate_delay_ms(2) == 40.0
    assert policy.calculate_delay_ms(3) == 80.0
    assert policy.calculate_delay_ms(4) == 80.0  # Capped at max_delay_ms


@pytest.mark.asyncio
async def test_execute_with_retry_eventual_success():
    call_count = 0

    async def flaky_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Return HTTP 500
            return httpx.Response(500, json={"error": "transient"})
        return httpx.Response(200, json={"status": "ok"})

    policy = RetryPolicy(max_retries=3, base_delay_ms=5.0, jitter=False)
    result = await execute_with_retry(flaky_call, policy)

    assert result.attempts == 3
    assert result.response is not None
    assert result.response.status_code == 200
    assert len(result.retry_delays_ms) == 2


# -----------------------------------------------------------------------------
# 3. Integration Tests: Service A /trigger with Resilience Pipeline
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_a_strict_timeout_abortion():
    """FR-2.1: Verify Service A aborts request when downstream latency exceeds strict timeout."""
    b_transport = ASGITransport(app=service_b_app)
    b_client = AsyncClient(transport=b_transport, base_url="http://service-b:8001")
    service_a_app.state.http_client = b_client
    await service_a_app.state.circuit_breaker.reset()

    a_transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=a_transport, base_url="http://service-a:8000") as a_client:
        # Downstream delay 500ms, but Service A timeout set strictly to 100ms
        start = time.perf_counter()
        response = await a_client.post(
            "/trigger",
            json={
                "latency_ms": 500,
                "failure_rate_pct": 0.0,
                "timeout_ms": 100,
                "use_retry": False,  # Isolate timeout without retrying
                "use_circuit_breaker": False,
            },
        )
        duration_ms = (time.perf_counter() - start) * 1000.0

        assert response.status_code == 504
        data = response.json()
        assert data["status"] == "timeout"
        assert duration_ms < 300.0  # Aborted quickly around 100ms, far below 500ms


@pytest.mark.asyncio
async def test_service_a_automated_retries_on_failure():
    """FR-2.2: Verify Service A retries on transient downstream failures."""
    b_transport = ASGITransport(app=service_b_app)
    b_client = AsyncClient(transport=b_transport, base_url="http://service-b:8001")
    service_a_app.state.http_client = b_client
    await service_a_app.state.circuit_breaker.reset()

    a_transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=a_transport, base_url="http://service-a:8000") as a_client:
        response = await a_client.post(
            "/trigger",
            json={
                "latency_ms": 5,
                "failure_rate_pct": 100.0,
                "max_retries": 2,
                "use_circuit_breaker": False,
            },
        )
        assert response.status_code == 502
        data = response.json()
        assert data["resilience"]["attempts"] == 3  # Initial attempt + 2 retries
        assert len(data["resilience"]["retry_delays_ms"]) == 2


@pytest.mark.asyncio
async def test_service_a_circuit_breaker_fast_fallback():
    """FR-2.3: Verify Circuit Breaker trips and returns fast fallback in <50ms."""
    b_transport = ASGITransport(app=service_b_app)
    b_client = AsyncClient(transport=b_transport, base_url="http://service-b:8001")
    service_a_app.state.http_client = b_client

    # Configure small threshold and reset
    cb: CircuitBreaker = service_a_app.state.circuit_breaker
    cb.failure_threshold = 2
    cb.recovery_timeout_seconds = 2.0
    await cb.reset()

    a_transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=a_transport, base_url="http://service-a:8000") as a_client:
        # Trip the breaker with 2 consecutive failures
        for _ in range(2):
            await a_client.post(
                "/trigger",
                json={"latency_ms": 5, "failure_rate_pct": 100.0, "use_retry": False},
            )

        assert cb.state == BreakerState.OPEN

        # Next call must hit open breaker and return fallback in <50ms
        start = time.perf_counter()
        resp = await a_client.post(
            "/trigger",
            json={"latency_ms": 5000, "failure_rate_pct": 0.0},  # Even with 5s downstream delay requested
        )
        duration_ms = (time.perf_counter() - start) * 1000.0

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded_fallback"
        assert data["resilience"]["circuit_breaker_tripped"] is True
        assert duration_ms < 50.0  # Must be fast fallback satisfying PRD criteria


@pytest.mark.asyncio
async def test_circuit_breaker_status_and_reset_endpoints():
    a_transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=a_transport, base_url="http://service-a:8000") as client:
        status_resp = await client.get("/circuit-breaker")
        assert status_resp.status_code == 200
        assert "state" in status_resp.json()

        reset_resp = await client.post("/circuit-breaker/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["status"] == "reset"
        assert reset_resp.json()["circuit_breaker"]["state"] == "CLOSED"

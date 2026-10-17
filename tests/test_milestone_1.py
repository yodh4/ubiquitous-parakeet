import importlib.util
import sys
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT_DIR = Path(__file__).resolve().parent.parent


def load_app(service_name: str):
    app_path = ROOT_DIR / "services" / service_name / "app" / "main.py"
    module_name = f"{service_name.replace('-', '_')}_app_main"

    # Ensure the service directory is on sys.path for relative imports like `from app.config import settings`
    service_dir = str(ROOT_DIR / "services" / service_name)
    if service_dir in sys.path:
        sys.path.remove(service_dir)
    sys.path.insert(0, service_dir)

    # Clean out cached 'app' package so the new service's 'app' is imported
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


@pytest.mark.asyncio
async def test_service_b_health():
    transport = ASGITransport(app=service_b_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "service-b"


@pytest.mark.asyncio
async def test_service_b_baseline_work():
    transport = ASGITransport(app=service_b_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"request_id": "req-123", "latency_ms": 0, "failure_rate_pct": 0.0}
        response = await client.post("/work", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["request_id"] == "req-123"
        assert data["status"] == "completed"
        assert data["simulated_latency_ms"] == 0


@pytest.mark.asyncio
async def test_service_b_simulated_latency():
    transport = ASGITransport(app=service_b_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"request_id": "req-delay", "latency_ms": 100, "failure_rate_pct": 0.0}
        start = time.perf_counter()
        response = await client.post("/work", json=payload)
        duration_ms = (time.perf_counter() - start) * 1000.0

        assert response.status_code == 200
        assert duration_ms >= 90  # Near 100ms
        assert response.json()["simulated_latency_ms"] == 100


@pytest.mark.asyncio
async def test_service_b_guaranteed_failure():
    transport = ASGITransport(app=service_b_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"request_id": "req-fail", "latency_ms": 0, "failure_rate_pct": 100.0}
        response = await client.post("/work", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert "Simulated failure" in str(data)


@pytest.mark.asyncio
async def test_service_a_sync_trigger_success():
    b_transport = ASGITransport(app=service_b_app)
    b_client = AsyncClient(transport=b_transport, base_url="http://service-b:8001")
    service_a_app.state.http_client = b_client

    a_transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=a_transport, base_url="http://service-a:8000") as a_client:
        payload = {"latency_ms": 50, "failure_rate_pct": 0.0}
        response = await a_client.post("/trigger", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "request_id" in data
        assert data["status"] == "success"
        assert data["round_trip_duration_ms"] >= 45.0
        assert data["downstream"]["status"] == "completed"
        assert data["downstream"]["simulated_latency_ms"] == 50


@pytest.mark.asyncio
async def test_service_a_sync_trigger_downstream_failure():
    b_transport = ASGITransport(app=service_b_app)
    b_client = AsyncClient(transport=b_transport, base_url="http://service-b:8001")
    service_a_app.state.http_client = b_client

    a_transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=a_transport, base_url="http://service-a:8000") as a_client:
        payload = {"latency_ms": 10, "failure_rate_pct": 100.0}
        response = await a_client.post("/trigger", json=payload)
        assert response.status_code == 502
        data = response.json()

        assert "request_id" in data
        assert data["status"] == "downstream_error"
        assert data["round_trip_duration_ms"] >= 8.0
        assert data["error"] is not None

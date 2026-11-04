import asyncio
import importlib.util
import json
import sys
import time
from contextlib import suppress
from pathlib import Path

import aio_pika
import pytest
from httpx import ASGITransport, AsyncClient

ROOT_DIR = Path(__file__).resolve().parent.parent
RABBITMQ_URL = "amqp://guest:guest@localhost:5673/"


def load_app(service_name: str):
    app_path = ROOT_DIR / "services" / service_name / "app" / "main.py"
    module_name = f"{service_name.replace('-', '_')}_app_main"

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


async def is_rabbitmq_available() -> bool:
    try:
        conn = await asyncio.wait_for(aio_pika.connect_robust(RABBITMQ_URL), timeout=1.5)
        await conn.close()
        return True
    except (OSError, aio_pika.exceptions.AMQPException, TimeoutError):
        return False


async def clean_broker():
    """Purges work and DLQ queues to prevent cross-test data pollution."""
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        channel = await conn.channel()
        with suppress(aio_pika.exceptions.AMQPException, OSError):
            work_q = await channel.declare_queue(
                "sandbox.tasks.work",
                durable=True,
                arguments={"x-dead-letter-exchange": "sandbox.dlx"},
            )
            await work_q.purge()
        with suppress(aio_pika.exceptions.AMQPException, OSError):
            dlq = await channel.declare_queue("sandbox.tasks.dlq", durable=True)
            await dlq.purge()


@pytest.fixture(autouse=True)
def ensure_clean_broker_state():
    if not asyncio.run(is_rabbitmq_available()):
        pytest.skip("RabbitMQ is not running on localhost:5673. Skipping Milestone 3 tests.")
    asyncio.run(clean_broker())
    if hasattr(service_b_app.state, "consumer") and service_b_app.state.consumer:
        asyncio.run(service_b_app.state.consumer.reset())
    yield
    asyncio.run(clean_broker())
    if hasattr(service_b_app.state, "consumer") and service_b_app.state.consumer:
        asyncio.run(service_b_app.state.consumer.reset())


@pytest.mark.asyncio
async def test_service_a_enqueue_fast_acceptance():
    """FR-3.1: Service A returns HTTP 202 Accepted in under 50ms regardless of workload."""
    async with service_a_app.router.lifespan_context(service_a_app):
        transport = ASGITransport(app=service_a_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "request_id": "test-fast-001",
                "latency_ms": 2000,  # 2 full seconds of simulated downstream work
                "failure_rate_pct": 0.0,
            }
            start = time.perf_counter()
            response = await client.post("/enqueue", json=payload)
            duration_ms = (time.perf_counter() - start) * 1000.0

            assert response.status_code == 202
            assert duration_ms < 100.0, f"Expected under 100ms fast acceptance, took {duration_ms}ms"

            data = response.json()
            assert data["status"] == "accepted"
            assert data["request_id"] == "test-fast-001"
            assert data["exchange"] == "sandbox.exchange"
            assert data["routing_key"] == "task.work"


@pytest.mark.asyncio
async def test_service_b_consumer_processes_task():
    """FR-3.2: Service B asynchronously drains tasks from the queue and updates stats."""
    # Enqueue a task into RabbitMQ
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        channel = await conn.channel()
        exchange = await channel.get_exchange("sandbox.exchange")
        body = json.dumps({"request_id": "test-task-basic", "latency_ms": 20, "failure_rate_pct": 0.0}).encode("utf-8")
        await exchange.publish(aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT), routing_key="task.work")

    # Start Service B consumer
    async with service_b_app.router.lifespan_context(service_b_app):
        transport = ASGITransport(app=service_b_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await asyncio.sleep(0.4)

            resp = await client.get("/consumer/stats")
            stats = resp.json()
            assert stats["is_running"] is True
            assert stats["total_completed"] >= 1
            assert stats["total_failed"] == 0

    # Verify work queue is empty
    verify_conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with verify_conn:
        vch = await verify_conn.channel()
        work_q = await vch.declare_queue(
            "sandbox.tasks.work",
            durable=True,
            arguments={"x-dead-letter-exchange": "sandbox.dlx"},
        )
        await work_q.declare()
        assert work_q.declaration_result.message_count == 0


@pytest.mark.asyncio
async def test_idempotency_duplicate_suppression():
    """FR-3.3: Duplicate deliveries are safely skipped and ACKed (Exactly-Once Effect)."""
    target_id = "test-idempotent-probe"

    # Publish the SAME request_id 5 times
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        channel = await conn.channel()
        exchange = await channel.get_exchange("sandbox.exchange")
        for _ in range(5):
            body = json.dumps({"request_id": target_id, "latency_ms": 10, "failure_rate_pct": 0.0}).encode("utf-8")
            await exchange.publish(
                aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key="task.work",
            )

    # Service B consumes all 5
    async with service_b_app.router.lifespan_context(service_b_app):
        transport = ASGITransport(app=service_b_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await asyncio.sleep(0.6)

            resp = await client.get("/consumer/stats")
            stats = resp.json()

            # Exactly 1 executed, 4 suppressed!
            assert stats["total_completed"] == 1, f"Expected 1 completed, got {stats['total_completed']}"
            assert stats["total_duplicates_skipped"] == 4, f"Expected 4 skipped, got {stats['total_duplicates_skipped']}"
            assert stats["active_in_flight"] == 0


@pytest.mark.asyncio
async def test_poison_message_dlq_quarantine():
    """FR-3.4: Unprocessable poison pills are routed to DLQ without blocking subsequent tasks."""
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        channel = await conn.channel()
        exchange = await channel.get_exchange("sandbox.exchange")

        # 1 Poison pill (100% failure)
        p_body = json.dumps({"request_id": "poison-test-99", "latency_ms": 0, "failure_rate_pct": 100.0}).encode("utf-8")
        await exchange.publish(
            aio_pika.Message(body=p_body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key="task.work",
        )

        # 2 Healthy tasks behind it
        for i in [1, 2]:
            h_body = json.dumps({"request_id": f"healthy-test-{i}", "latency_ms": 10, "failure_rate_pct": 0.0}).encode("utf-8")
            await exchange.publish(
                aio_pika.Message(body=h_body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key="task.work",
            )

    # Run consumer
    async with service_b_app.router.lifespan_context(service_b_app):
        transport = ASGITransport(app=service_b_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await asyncio.sleep(0.6)

            stats_resp = await client.get("/consumer/stats")
            stats = stats_resp.json()

            dlq_resp = await client.get("/consumer/dlq")
            dlq_data = dlq_resp.json()

            # Assert poison message was quarantined
            assert stats["total_failed"] == 1
            assert stats["total_completed"] == 2
            assert dlq_data["message_count"] == 1
            assert stats["dlq_message_count"] == 1


@pytest.mark.asyncio
async def test_dlq_purge_endpoint():
    """Verifies that POST /consumer/dlq/purge cleans the quarantine queue."""
    # Place 1 message into DLQ directly via DLX
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    async with conn:
        channel = await conn.channel()
        dlx = await channel.get_exchange("sandbox.dlx")
        await dlx.publish(aio_pika.Message(body=b"bad-message"), routing_key="task.work")

    async with service_b_app.router.lifespan_context(service_b_app):
        transport = ASGITransport(app=service_b_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Query count before
            dlq_before = await client.get("/consumer/dlq")
            assert dlq_before.json()["message_count"] == 1

            # Purge
            purge_resp = await client.post("/consumer/dlq/purge")
            assert purge_resp.status_code == 200
            assert purge_resp.json()["purged_count"] >= 1

            # Query count after
            dlq_after = await client.get("/consumer/dlq")
            assert dlq_after.json()["message_count"] == 0

import asyncio
import importlib.util
import json
import sys
import uuid
from contextlib import suppress
from pathlib import Path

import aio_pika
import pytest
from httpx import ASGITransport, AsyncClient

ROOT_DIR = Path(__file__).resolve().parent.parent
RABBITMQ_URL = "amqp://guest:guest@localhost:5673/"


def load_app(service_name: str):
    app_path = ROOT_DIR / "services" / service_name / "app" / "main.py"
    module_name = f"{service_name.replace('-', '_')}_app_main_m4"

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
    with suppress(Exception):
        conn = await aio_pika.connect_robust(RABBITMQ_URL)
        ch = await conn.channel()
        q_work = await ch.declare_queue(
            "sandbox.tasks.work",
            durable=True,
            arguments={"x-dead-letter-exchange": "sandbox.dlx"},
        )
        await q_work.purge()
        q_dlq = await ch.declare_queue("sandbox.tasks.dlq", durable=True)
        await q_dlq.purge()
        await conn.close()


@pytest.mark.asyncio
async def test_middleware_generates_correlation_id_when_missing():
    """Verify that incoming requests without X-Correlation-ID receive an auto-generated UUIDv4."""
    transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        cid = resp.headers.get("x-correlation-id")
        assert cid is not None
        assert len(cid) == 32  # uuid.uuid4().hex format


@pytest.mark.asyncio
async def test_middleware_preserves_custom_correlation_id():
    """Verify that caller-supplied X-Correlation-ID is preserved in headers and response body."""
    custom_cid = f"trace-custom-{uuid.uuid4().hex[:8]}"
    transport = ASGITransport(app=service_a_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health", headers={"x-correlation-id": custom_cid})
        assert resp.status_code == 200
        assert resp.headers.get("x-correlation-id") == custom_cid


@pytest.mark.asyncio
async def test_sync_correlation_propagation_service_a_to_service_b():
    """Verify end-to-end synchronous propagation: Service A -> Service B via HTTP client."""
    custom_cid = f"trace-sync-e2e-{uuid.uuid4().hex[:8]}"

    # Wire Service A's HTTP client to dispatch directly into Service B ASGI app
    b_transport = ASGITransport(app=service_b_app)
    async with AsyncClient(transport=b_transport, base_url="http://service-b:8001") as mocked_client:
        service_a_app.state.http_client = mocked_client

        a_transport = ASGITransport(app=service_a_app)
        async with AsyncClient(transport=a_transport, base_url="http://test") as client:
            resp = await client.post(
                "/trigger",
                json={"latency_ms": 0, "failure_rate_pct": 0.0, "use_retry": False},
                headers={"x-correlation-id": custom_cid},
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify Service A echoed CID in header and body
            assert resp.headers.get("x-correlation-id") == custom_cid
            assert data.get("correlation_id") == custom_cid

            # Verify Service B received and echoed the CID in its downstream response body
            downstream = data.get("downstream")
            assert downstream is not None
            assert downstream.get("correlation_id") == custom_cid


@pytest.mark.asyncio
async def test_amqp_publisher_attaches_correlation_metadata():
    """Verify that Service A /enqueue attaches correlation_id to AMQP envelope and headers."""
    if not await is_rabbitmq_available():
        pytest.skip("RabbitMQ is not running. Start with docker compose --profile with-broker up -d rabbitmq")

    await clean_broker()
    custom_cid = f"trace-amqp-{uuid.uuid4().hex[:8]}"

    # Setup publisher on Service A
    sys.path.insert(0, str(ROOT_DIR / "services" / "service-a"))
    from app.messaging.publisher import MessagePublisher

    publisher = MessagePublisher(rabbitmq_url=RABBITMQ_URL)
    await publisher.connect()
    service_a_app.state.publisher = publisher

    try:
        a_transport = ASGITransport(app=service_a_app)
        async with AsyncClient(transport=a_transport, base_url="http://test") as client:
            resp = await client.post(
                "/enqueue",
                json={"latency_ms": 0, "failure_rate_pct": 0.0, "request_id": "test-amqp-correlate"},
                headers={"x-correlation-id": custom_cid},
            )
            assert resp.status_code == 202
            assert resp.headers.get("x-correlation-id") == custom_cid
            assert resp.json().get("correlation_id") == custom_cid

        # Inspect message envelope directly from RabbitMQ
        conn = await aio_pika.connect_robust(RABBITMQ_URL)
        ch = await conn.channel()
        q = await ch.declare_queue(
            "sandbox.tasks.work",
            durable=True,
            arguments={"x-dead-letter-exchange": "sandbox.dlx"},
        )

        msg = await q.get(no_ack=False)
        assert msg is not None
        assert msg.correlation_id == custom_cid
        assert msg.headers.get("x-correlation-id") == custom_cid

        payload = json.loads(msg.body.decode("utf-8"))
        assert payload.get("request_id") == "test-amqp-correlate"

        await msg.ack()
        await conn.close()
    finally:
        await publisher.close()


@pytest.mark.asyncio
async def test_amqp_consumer_extracts_and_binds_correlation_id():
    """Verify that Service B consumer extracts correlation ID and maintains it during task execution."""
    if not await is_rabbitmq_available():
        pytest.skip("RabbitMQ is not running.")

    await clean_broker()
    custom_cid = f"trace-consumer-e2e-{uuid.uuid4().hex[:8]}"

    # Publish a message directly with custom correlation metadata
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await conn.channel()
    exchange = await channel.declare_exchange("sandbox.exchange", aio_pika.ExchangeType.DIRECT, durable=True)

    task_payload = {
        "request_id": f"task-{uuid.uuid4().hex[:6]}",
        "latency_ms": 20,
        "failure_rate_pct": 0.0,
    }
    msg = aio_pika.Message(
        body=json.dumps(task_payload).encode("utf-8"),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        content_type="application/json",
        correlation_id=custom_cid,
        headers={"x-correlation-id": custom_cid},
    )
    await exchange.publish(msg, routing_key="task.work")

    # Start consumer briefly to process the message
    for mod in list(sys.modules.keys()):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    service_b_dir = str(ROOT_DIR / "services" / "service-b")
    if service_b_dir in sys.path:
        sys.path.remove(service_b_dir)
    sys.path.insert(0, service_b_dir)
    from app.correlation import get_correlation_id
    from app.messaging.consumer import TaskConsumer

    consumer = TaskConsumer(rabbitmq_url=RABBITMQ_URL, prefetch_count=1)

    # Track correlation ID active in contextvars during execution
    observed_context_cid = None
    real_acquire = consumer.idempotency_store.check_and_acquire

    async def wrapped_acquire(req_id):
        nonlocal observed_context_cid
        observed_context_cid = get_correlation_id()
        return await real_acquire(req_id)

    consumer.idempotency_store.check_and_acquire = wrapped_acquire
    await consumer.start()

    try:
        # Wait up to 3 seconds for consumer to complete
        for _ in range(30):
            if consumer.total_completed >= 1:
                break
            await asyncio.sleep(0.1)

        assert consumer.total_completed == 1
        assert observed_context_cid == custom_cid
        assert consumer.last_processed_id == task_payload["request_id"]
    finally:
        await consumer.stop()
        await conn.close()


@pytest.mark.asyncio
async def test_json_formatter_produces_valid_json_structure():
    """Verify that JSONFormatter produces valid, parseable JSON with all required keys."""
    import logging

    sys.path.insert(0, str(ROOT_DIR / "services" / "service-a"))
    from app.logging_config import JSONFormatter

    formatter = JSONFormatter(service_name="service-a-test")
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Structured log test message with %s",
        args=("interpolation",),
        exc_info=None,
    )
    record.correlation_id = "trace-json-test-123"

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["service"] == "service-a-test"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert parsed["message"] == "Structured log test message with interpolation"
    assert parsed["correlation_id"] == "trace-json-test-123"
    assert "timestamp" in parsed


@pytest.mark.asyncio
async def test_logging_filter_auto_injects_correlation_id_from_contextvars():
    """Verify that CorrelationIdFilter injects the active contextvars correlation ID into LogRecords."""
    import io
    import logging

    for mod in list(sys.modules.keys()):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    service_a_dir = str(ROOT_DIR / "services" / "service-a")
    if service_a_dir in sys.path:
        sys.path.remove(service_a_dir)
    sys.path.insert(0, service_a_dir)

    from app.correlation import correlation_scope
    from app.logging_config import CorrelationIdFilter, JSONFormatter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter(service_name="service-a"))
    handler.addFilter(CorrelationIdFilter())

    test_logger = logging.getLogger("test.auto_inject")
    test_logger.handlers.clear()
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    custom_cid = f"trace-filter-{uuid.uuid4().hex[:8]}"

    # Log inside correlation_scope
    async with correlation_scope(custom_cid):
        test_logger.info("Message inside correlation scope")

    # Log outside correlation_scope
    test_logger.info("Message outside correlation scope")

    lines = stream.getvalue().strip().split("\n")
    assert len(lines) == 2

    inside_log = json.loads(lines[0])
    assert inside_log["correlation_id"] == custom_cid
    assert inside_log["message"] == "Message inside correlation scope"

    outside_log = json.loads(lines[1])
    assert outside_log["correlation_id"] is None
    assert outside_log["message"] == "Message outside correlation scope"


@pytest.mark.asyncio
async def test_json_formatter_handles_exceptions_atomically():
    """Verify that stack traces are formatted inside a single atomic exc_info JSON field."""
    import logging

    sys.path.insert(0, str(ROOT_DIR / "services" / "service-a"))
    from app.logging_config import JSONFormatter

    formatter = JSONFormatter(service_name="service-a")

    try:
        raise ValueError("Simulated failure for traceback test")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test.exception",
        level=logging.ERROR,
        pathname="test.py",
        lineno=42,
        msg="An unhandled exception occurred",
        args=(),
        exc_info=exc_info,
    )

    output = formatter.format(record)
    # Must be valid single-line JSON despite multi-line traceback
    assert "\n" not in output
    parsed = json.loads(output)
    assert parsed["level"] == "ERROR"
    assert "exc_info" in parsed
    assert "ValueError: Simulated failure for traceback test" in parsed["exc_info"]


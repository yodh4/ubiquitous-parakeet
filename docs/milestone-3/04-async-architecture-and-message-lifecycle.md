# Part 4: Async Architecture & Message Lifecycle

This document presents the complete architectural specification for **Milestone 3: Asynchronous Decoupling & Reliability**, detailing the end-to-end message lifecycle, operational sequence diagrams, and Python implementation structure using **`aio-pika`**.

---

## 1. System Architecture Overview

In Milestone 3, client traffic is no longer tethered to downstream execution:

```mermaid
flowchart TD
    Client(["External Client"]) -->|"1. POST /enqueue"| SvcA["Service A (Ingress Node)"]
    SvcA -->|"2. Return HTTP 202 Accepted (under 10ms)"| Client
    SvcA -->|"3. AMQP Publish (task.work)"| BrokerEx["RabbitMQ Exchange\nsandbox.exchange (Direct)"]

    BrokerEx -->|"Binding: task.work"| WorkQ[("Main Work Queue\nsandbox.tasks.work\nx-dead-letter-exchange: sandbox.dlx")]

    subgraph SvcB_Process ["Service B (Worker Process)"]
        ConsumerTask["Async Background Consumer Task\n(prefetch_count = 5)"]
        IdemStore[("Idempotency Store\nProcessed Request IDs")]
        WorkEngine["Workload Simulator\n(asyncio.sleep / random failure)"]
    end

    WorkQ -->|"Deliver Message"| ConsumerTask
    ConsumerTask -->|"Lookup Request ID"| IdemStore
    IdemStore -->|"New Message"| WorkEngine
    IdemStore -->|"Duplicate Message"| AckSkip["Skip Work & Ack Message"]

    WorkEngine -->|"Success"| AckDone["Ack Message (Basic.Ack)"]
    WorkEngine -->|"Simulated Error / Failure"| NackDead["Nack Message without Requeue\n(Basic.Nack requeue=False)"]

    NackDead --> DLX["Dead Letter Exchange\nsandbox.dlx"]
    DLX --> DLQ[("Dead Letter Queue\nsandbox.tasks.dlq")]

    %% Distinct High-Contrast Layer Styling
    style SvcA fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style BrokerEx fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style WorkQ fill:#1e293b,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style SvcB_Process fill:#022c22,stroke:#059669,stroke-width:2px,color:#ffffff
    style ConsumerTask fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style IdemStore fill:#0f172a,stroke:#64748b,stroke-width:2px,color:#ffffff
    style WorkEngine fill:#047857,stroke:#34d399,stroke-width:2px,color:#ffffff
    style DLX fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#ffffff
    style DLQ fill:#450a0a,stroke:#dc2626,stroke-width:2px,color:#ffffff
    style Client fill:#334155,stroke:#94a3b8,stroke-width:2px,color:#ffffff
```

---

## 2. Operational Sequence Diagrams

### Scenario 1: Happy Path Asynchronous Ingestion & Background Execution

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant A as Service A (Ingress)
    participant Broker as RabbitMQ (sandbox.tasks.work)
    participant B as Service B (Consumer Worker)

    Client->>A: POST /enqueue {"latency_ms": 1000, "failure_rate_pct": 0}
    activate A
    Note over A: 1. Generate UUID request_id<br/>2. Package message envelope
    A->>Broker: Publish message (delivery_mode=PERSISTENT)
    A-->>Client: HTTP 202 Accepted {"status": "accepted", "request_id": "..."}
    deactivate A
    Note over Client: Client interaction finishes in under 10ms!

    Note over Broker,B: Background Consumption (Decoupled in Time)
    Broker->>B: Deliver Task (request_id="req-01")
    activate B
    Note over B: 1. Idempotency Check: "req-01" unseen<br/>2. Record "req-01" in cache<br/>3. Execute simulated latency (1,000ms)
    B-->>Broker: Basic.Ack
    deactivate B
    Note over Broker: Task removed from queue. Complete!
```

---

### Scenario 2: Duplicate Delivery Suppression (Idempotent Deduplication)

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Broker as RabbitMQ (sandbox.tasks.work)
    participant B as Service B (Consumer Worker)

    Note over Client,Broker: Client or retry storm publishes same request_id twice
    Broker->>B: Deliver Task Attempt 1 (request_id="req-dup")
    activate B
    Note over B: First time seen: Execute work & record ID
    B-->>Broker: Basic.Ack
    deactivate B

    Broker->>B: Deliver Duplicate Task (request_id="req-dup", redelivered=True)
    activate B
    Note over B: 1. Idempotency Check: "req-dup" ALREADY IN CACHE!<br/>2. SKIP simulated work entirely (0ms overhead)<br/>3. Increment duplicate counter
    B-->>Broker: Basic.Ack (Acknowledge & discard)
    deactivate B
    Note over B: Exactly-Once Effect Achieved! Zero duplicate side effects.
```

---

### Scenario 3: Poison Message Routing to Dead Letter Queue (DLQ)

```mermaid
sequenceDiagram
    autonumber
    participant WorkQ as Work Queue (sandbox.tasks.work)
    participant B as Service B (Consumer Worker)
    participant DLX as Dead Letter Exchange (sandbox.dlx)
    participant DLQ as Dead Letter Queue (sandbox.tasks.dlq)

    WorkQ->>B: Deliver Poison Task (failure_rate_pct = 100)
    activate B
    Note over B: Workload simulation triggers fatal error!
    B-->>WorkQ: Basic.Nack(requeue=False)
    deactivate B

    Note over WorkQ,DLX: RabbitMQ detects nack without requeue.<br/>Routes message to dead letter exchange.
    WorkQ->>DLX: Forward message with x-death header
    DLX->>DLQ: Enqueue into sandbox.tasks.dlq
    Note over DLQ: Message safely quarantined for inspection.<br/>Main work queue remains 100% operational!
```

---

## 3. Technology Choice: `aio-pika`

For interacting with RabbitMQ from FastAPI, we select **`aio-pika`**:
* **Why not `pika`?** Standard `pika` is synchronous and blocking. Calling it in an async FastAPI route freezes the event loop.
* **Why `aio-pika`?** Built specifically for Python's `asyncio` event loop. It provides non-blocking connection pooling, robust channel recycling, and native Python context managers (`async with message.process():`).

---

## 4. Code Structure Plan for Milestone 3

```text
services/
├── service-a/
│   └── app/
│       ├── config.py                 # RabbitMQ connection URL and exchange names
│       ├── main.py                   # POST /enqueue endpoint and broker lifespan
│       ├── schemas.py                # EnqueueRequest and EnqueueResponse schemas
│       └── messaging/
│           ├── __init__.py
│           └── publisher.py          # aio-pika persistent connection and publisher pool
│
└── service-b/
    └── app/
        ├── config.py                 # RabbitMQ connection URL and prefetch settings
        ├── main.py                   # FastAPI app with telemetry (GET /consumer/stats)
        ├── schemas.py                # Task telemetry schemas
        └── messaging/
            ├── __init__.py
            ├── consumer.py           # Background consumption loop (basic_consume)
            ├── idempotency.py        # Thread-safe in-memory deduplication cache with TTL
            └── topology.py           # Broker setup: exchanges, work queue, DLX, DLQ
```

---

## 5. Acceptance Criteria Verification Plan

| PRD Acceptance Requirement | Test Scenario | Verification Method |
| :--- | :--- | :--- |
| **Load Leveling (Buffer)** | Burst of **500 requests** sent in 1 second to Service A while Service B is limited to **10 requests/sec**. | Verify 0% error rate at Service A (`202 Accepted`), maximum memory stability at Service B, and steady queue draining over 50 seconds. |
| **Exactly-Once Effect** | Publish the exact same `request_id` **5 times** to RabbitMQ. | Verify Service B executes the workload exactly **once** and suppresses/acknowledges the remaining **4 attempts**. |
| **Poison Message Isolation** | Send a task with `failure_rate_pct = 100.0`. | Verify Service B rejects the message, RabbitMQ routes it to `sandbox.tasks.dlq`, and subsequent tasks in `sandbox.tasks.work` are not blocked. |

---

*This concludes the Milestone 3 architectural and learning documentation. We are ready to begin implementation!*

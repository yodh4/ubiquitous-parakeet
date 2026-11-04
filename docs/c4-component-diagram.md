# C4 Level 3: Component Diagram

This document presents the **C4 Component Diagram (Level 3)** for the **Zero-Logic Microservices Architecture Sandbox**.

In the C4 model, a **Component** is a structural building block within a container (such as a router controller, background task loop, or resilience state machine) that encapsulates specific responsibilities.

---

## 1. Visual Component Diagram

```mermaid
flowchart TD
    Client(["👤 External Client / Test Harness"])

    subgraph ServiceA_Container ["📦 Container: Service A (Ingress & Producer)"]
        RouterA["⚙️ Component: Ingress API Router<br/>[FastAPI Controllers]<br/>Routes /trigger, /enqueue, /circuit-breaker"]

        subgraph ResilienceEngine ["Component: Resilience Engine (The Onion Model)"]
            CB["🛡️ Circuit Breaker FSM<br/>[CLOSED / OPEN / HALF-OPEN]<br/>Fast degraded fallback under 5ms"]
            RetryEng["🔄 Retry Engine<br/>[Exponential Backoff + Full Jitter]<br/>Prevents synchronized retry storms"]
            TimeoutMgr["⏱️ Socket Timeout Manager<br/>[httpx.AsyncClient connection pool]<br/>Per-attempt connect and read deadlines"]
            CB --> RetryEng --> TimeoutMgr
        end

        Publisher["📤 Component: Message Publisher<br/>[aio-pika.RobustConnection / Channel]<br/>Packages persistent message envelopes and publishes to AMQP"]

        RouterA -->|"Sync Path"| CB
        RouterA -->|"Async Path"| Publisher
    end

    subgraph Broker_Container ["📦 Container: RabbitMQ Broker (AMQP 0-9-1 Topology)"]
        MainEx["🔀 Component: Main Exchange<br/>[sandbox.exchange - Direct]"]
        WorkQ[("📥 Component: Work Queue Buffer<br/>[sandbox.tasks.work]<br/>x-dead-letter-exchange: sandbox.dlx")]
        DLX["🔀 Component: Dead Letter Exchange<br/>[sandbox.dlx - Direct]"]
        DLQ[("🛑 Component: Dead Letter Queue<br/>[sandbox.tasks.dlq]<br/>Holds quarantined poison pills")]

        MainEx -->|"Binding: task.work"| WorkQ
        WorkQ -.->|"On NACK requeue=False"| DLX
        DLX -->|"Binding: task.work"| DLQ
    end

    subgraph ServiceB_Container ["📦 Container: Service B (Worker & Consumer)"]
        RouterB["⚙️ Component: Worker API Router<br/>[FastAPI /consumer/stats & /work]"]
        Consumer["📥 Component: Background TaskConsumer<br/>[aio-pika basic_consume]<br/>Prefetch=5 controlled concurrency, manual Ack/Nack"]
        IdemStore["🔒 Component: Idempotency Store<br/>[In-Flight Set + TTL Cache]<br/>Atomic lease acquisition and duplicate suppression"]
        WorkSim["⚡ Component: Workload Simulator<br/>[asyncio.sleep & random fault injection]<br/>Simulates processing delay or runtime crashes"]

        Consumer -->|"1. Check & acquire"| IdemStore
        IdemStore -->|"2. New task"| WorkSim
        IdemStore -->|"2. Duplicate"| Consumer
        WorkSim -->|"3. Mark completed"| IdemStore
        WorkSim -->|"4. Work outcome"| Consumer
    end

    Client -->|"POST /enqueue (HTTP:8000)"| RouterA
    Client -->|"POST /trigger (HTTP:8000)"| RouterA
    TimeoutMgr -->|"HTTP POST /work (Port 8001)"| RouterB
    Publisher -->|"AMQP Publish: task.work"| MainEx
    WorkQ -->|"AMQP Controlled Push (prefetch=5)"| Consumer

    %% High-Contrast C4 Styling adhering to DOCUMENTATION_RULES.md
    style ServiceA_Container fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style Broker_Container fill:#1e293b,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style ServiceB_Container fill:#022c22,stroke:#059669,stroke-width:2px,color:#ffffff
    style ResilienceEngine fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style RouterA fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style Publisher fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style CB fill:#92400e,stroke:#fbbf24,stroke-width:2px,color:#ffffff
    style RetryEng fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style TimeoutMgr fill:#4c1d95,stroke:#8b5cf6,stroke-width:2px,color:#ffffff
    style MainEx fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style WorkQ fill:#0f172a,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style DLX fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#ffffff
    style DLQ fill:#450a0a,stroke:#dc2626,stroke-width:2px,color:#ffffff
    style RouterB fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style Consumer fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style IdemStore fill:#0f172a,stroke:#64748b,stroke-width:2px,color:#ffffff
    style WorkSim fill:#047857,stroke:#34d399,stroke-width:2px,color:#ffffff
    style Client fill:#334155,stroke:#94a3b8,stroke-width:2px,color:#ffffff
```

---

## 2. Component Breakdown by Container

### Container 1: Service A (Ingress & Producer)

| Component | Path / Module | Responsibility |
| :--- | :--- | :--- |
| **Ingress API Router** | `services/service-a/app/main.py` | FastAPI route handlers for `/enqueue`, `/trigger`, `/circuit-breaker`, and `/health`. Validates syntactic schemas (`EnqueueRequest`). |
| **Circuit Breaker** | `services/service-a/app/resilience/circuit_breaker.py` | 3-state Finite State Machine (`CLOSED`, `OPEN`, `HALF-OPEN`). Fast-fails in under 5ms without making network calls when downstream error thresholds are reached. |
| **Retry Engine** | `services/service-a/app/resilience/retry.py` | Retries transient HTTP errors using Exponential Backoff with Full Jitter: $\text{delay} = \text{random}(0, \text{base} \times 2^{\text{attempt}})$. |
| **Socket Timeout Manager** | `services/service-a/app/main.py` (via `httpx`) | Enforces per-attempt connect and read deadlines on outbound HTTP calls to protect upstream server thread pools. |
| **Message Publisher** | `services/service-a/app/messaging/publisher.py` | Maintains a long-lived AMQP connection/channel and publishes persistent, durable message frames to `sandbox.exchange`. |

---

### Container 2: RabbitMQ Broker (AMQP Topology)

| Component | Entity Name | Type / Properties | Responsibility |
| :--- | :--- | :--- | :--- |
| **Main Exchange** | `sandbox.exchange` | Direct Exchange (`durable=True`) | Central router that receives published tasks from Service A and matches binding keys. |
| **Main Work Queue** | `sandbox.tasks.work` | Durable FIFO Queue | Buffers tasks for Service B. Configured with `x-dead-letter-exchange: sandbox.dlx`. |
| **Dead Letter Exchange (DLX)** | `sandbox.dlx` | Direct Exchange (`durable=True`) | Receives rejected messages that failed processing in Service B without requeue. |
| **Dead Letter Queue (DLQ)** | `sandbox.tasks.dlq` | Durable FIFO Queue | Quarantines poison pills for inspection and post-mortem analysis. |

---

### Container 3: Service B (Worker & Consumer)

| Component | Path / Module | Responsibility |
| :--- | :--- | :--- |
| **Worker API Router** | `services/service-b/app/main.py` | FastAPI route handlers for `/consumer/stats`, `/consumer/dlq`, `/consumer/reset`, and `/work`. |
| **TaskConsumer** | `services/service-b/app/messaging/consumer.py` | Background async consumption loop running in lifespan. Enforces `prefetch_count=5` backpressure and sends manual `ACK`/`NACK`. |
| **Idempotency Store** | `services/service-b/app/messaging/idempotency.py` | Thread-safe deduplication store combining atomic in-flight leases and TTL sliding-window caching to guarantee the **Exactly-Once Effect**. |
| **Workload Simulator** | `services/service-b/app/messaging/consumer.py` | Executes configurable artificial delay (`asyncio.sleep`) and probabilistic failure injection (`random.uniform`). |
| **Topology Initializer** | `services/service-b/app/messaging/topology.py` | Blueprint constructor that idempotently declares exchanges, queues, DLX, DLQ, and bindings on startup. |

---

## 3. End-to-End Component Lifecycle

1. **Ingress & Publish:**
   * Client calls `POST /enqueue` on `RouterA`.
   * `RouterA` passes payload to `Publisher`.
   * `Publisher` formats a JSON envelope with a UUID `request_id`, marks it `DeliveryMode.PERSISTENT`, and flushes it to `MainEx` with routing key `task.work`.
   * `RouterA` immediately returns `HTTP 202 Accepted` to the Client.
2. **Buffering & Delivery:**
   * `MainEx` routes the message into `WorkQ`.
   * RabbitMQ pushes the task to `Consumer` only if Service B's active in-flight count is below `prefetch_count=5`.
3. **Execution & Idempotency:**
   * `Consumer` invokes `IdemStore.check_and_acquire(request_id)`.
   * **If Duplicate:** `Consumer` immediately ACKs without executing work.
   * **If New:** `Consumer` runs `WorkSim`.
4. **Completion or Quarantine:**
   * **Success:** `IdemStore.mark_completed(request_id)`, `Consumer` sends `basic_ack()`.
   * **Poison Failure:** `Consumer` catches exception, releases in-flight lease, and sends `basic_nack(requeue=False)`. RabbitMQ intercepts the rejected message and routes it via `DLX` into `DLQ`.

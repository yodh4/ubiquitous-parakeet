# Part 2: Delivery Guarantees & Idempotency

When transitioning from synchronous REST to asynchronous messaging, many developers assume that the message broker guarantees **"Exactly-Once Delivery"**. 

In distributed systems, **true network-level exactly-once delivery is physically impossible** (proven by the *Two Generals' Problem*). Modern message brokers (RabbitMQ, Apache Kafka, AWS SQS) provide **At-Least-Once Delivery**.

Because messages can and will be delivered more than once, consumer services must be designed using the **Idempotent Consumer Pattern** to achieve an *exactly-once processing effect*.

---

## 1. The Three Delivery Guarantees

```mermaid
flowchart TD
    subgraph AtMostOnce ["1. At-Most-Once (Best Effort)"]
        direction TB
        AMO1["Broker sends message to Worker"] --> AMO2["Broker deletes message IMMEDIATELY (auto-ack)"]
        AMO2 --> AMO3["Worker crashes before processing"]
        AMO3 --> AMO4["Result: Message is LOST FOREVER"]
    end

    subgraph AtLeastOnce ["2. At-Least-Once (Industry Standard)"]
        direction TB
        ALO1["Broker sends message to Worker"] --> ALO2["Worker executes task successfully"]
        ALO2 --> ALO3["Network blip drops the ACK packet on the wire"]
        ALO3 --> ALO4["Broker re-delivers to another Worker"]
        ALO4 --> ALO5["Result: Zero data loss, but DUPLICATES OCCUR"]
    end

    subgraph ExactlyOnceEffect ["3. Exactly-Once Effect (At-Least-Once + Idempotency)"]
        direction TB
        EO1["Duplicate message arrives at Worker"] --> EO2["Worker checks unique Request ID in Deduplication Store"]
        EO2 --> EO3["Worker skips work and sends ACK immediately"]
        EO3 --> EO4["Result: Exactly-Once business effect!"]
    end

    AtMostOnce ~~~ AtLeastOnce ~~~ ExactlyOnceEffect

    %% High-Contrast Subgraph Styling
    style AtMostOnce fill:#450a0a,stroke:#dc2626,stroke-width:2px,color:#ffffff
    style AtLeastOnce fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style ExactlyOnceEffect fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
```

### Breakdown of Guarantees:

| Guarantee | How It Works | Trade-off | Used When? |
| :--- | :--- | :--- | :--- |
| **At-Most-Once** | Auto-ack enabled (`no_ack=True`). Broker forgets message as soon as sent. | High speed, but **data loss is guaranteed** if workers crash. | High-frequency telemetry, non-critical metrics, GPS coordinates. |
| **At-Least-Once** | Manual ACKs. Message stays in queue until worker explicitly confirms. | **Zero message loss**, but consumers must handle duplicate messages. | **Standard for financial, order, and business processing**. |
| **Exactly-Once** | Theoretical ideal at the transport layer. | Impossible across distributed networks without application-level deduplication. | Achieved via **Idempotent Consumers**. |

---

## 2. Why Do Duplicate Messages Occur?

Duplicates are not an anomaly; they are a normal operational reality in distributed systems. Here are the two most common root causes:

### Cause A: Worker Crashes Right Before Sending the ACK
```mermaid
sequenceDiagram
    autonumber
    participant Queue as RabbitMQ Work Queue
    participant W1 as Worker Node 1
    participant W2 as Worker Node 2

    Queue->>W1: Deliver Task (request_id="req-123")
    activate W1
    Note over W1: 1. Worker executes business logic<br/>(e.g. Charges credit card $50)
    Note over W1: 2. Worker crashes (OOM / Power Cut / Network Drop)
    deactivate W1

    Note over Queue: RabbitMQ detects W1 disconnected without sending ACK!<br/>Message is returned to Queue.

    Queue->>W2: Re-deliver Task (request_id="req-123", redelivered=True)
    activate W2
    Note over W2: Without Idempotency: Worker 2 charges credit card A SECOND TIME!
    deactivate W2
```

### Cause B: Producer Retry During Network Hiccups
1. Service A publishes a message to RabbitMQ.
2. RabbitMQ writes the message to the queue.
3. The network connection drops before RabbitMQ's publisher confirmation reaches Service A.
4. Service A's retry engine (from Milestone 2) assumes the message was lost and publishes it a second time.
5. The queue now holds **two identical messages with the same payload**.

---

## 3. The Idempotent Consumer Pattern

### What is an Idempotent Operation?
Mathematically, an operation $f$ is **idempotent** if applying it multiple times yields the exact same state as applying it once:

$$f(f(x)) = f(x)$$

### The 4-Step Idempotency Protocol:

```mermaid
flowchart TD
    MsgIn["Incoming Message Received\n(request_id = 'req-123')"] --> CheckIdem{"Has request_id been processed?\n(Query Deduplication Store)"}

    CheckIdem -->|"YES (Duplicate Detected)"| LogDup["Log: Duplicate suppressed for req-123"]
    LogDup --> AckDup["Send Basic.Ack\n(Acknowledge & Discard)"]
    AckDup --> DoneDup(["No Work Executed (Zero Side Effects)"])

    CheckIdem -->|"NO (First Time Seen)"| RecordStore["Record request_id in Deduplication Store"]
    RecordStore --> ExecuteTask["Execute Workload Simulation\n(asyncio.sleep / compute)"]
    ExecuteTask --> AckSuccess["Send Basic.Ack\n(Mark Message Done)"]
    AckSuccess --> DoneSuccess(["Task Completed Successfully"])

    %% Semantic High-Contrast Styling
    style CheckIdem fill:#0f172a,stroke:#64748b,stroke-width:2px,color:#ffffff
    style LogDup fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style AckDup fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style RecordStore fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style ExecuteTask fill:#047857,stroke:#34d399,stroke-width:2px,color:#ffffff
    style AckSuccess fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
```

---

## 4. Deduplication Store Options in Production

To detect duplicates, Service B needs a mechanism to remember which `request_id` values it has already seen:

| Storage Type | Mechanism | Pros | Cons / Trade-offs |
| :--- | :--- | :--- | :--- |
| **In-Memory Cache (Sandbox)** | Thread-safe `set[str]` or `collections.OrderedDict` with TTL. | Zero external dependencies, sub-millisecond lookup. | Lost if the worker process restarts; isolated per worker instance. |
| **Distributed Cache (Redis)** | `SET request_id "processed" EX 86400 NX` | Shared across all worker nodes, automatic TTL expiration. | Requires Redis infrastructure; network hop overhead (1-2ms). |
| **Database Unique Constraint** | `INSERT INTO processed_tasks (id) VALUES (...) ON CONFLICT DO NOTHING` | **100% ACID consistency**; shares same transaction with business data. | Higher database write overhead; requires table cleanup cron. |

---

## 5. Summary & Checklist for Milestone 3

- [x] Accept that network messaging is fundamentally **At-Least-Once**.
- [x] Attach a unique `request_id` to every published message envelope.
- [x] Implement the **Idempotent Consumer Pattern** in Service B (`FR-3.3`).
- [x] Acknowledge duplicate messages immediately without executing workload to avoid queue blockage.
- [x] Verify the **Exactly-Once Effect**: Publishing the same `request_id` 5 times results in exactly 1 execution and 4 skips.

# Part 1: Message Broker & AMQP Fundamentals

To build reliable asynchronous microservices, we must understand how modern message brokers operate. In this project, we use **RabbitMQ**, the industry-standard implementation of the **AMQP 0-9-1 (Advanced Message Queuing Protocol)** specification.

Unlike simple Redis lists or HTTP webhooks, AMQP provides formal networking guarantees: dynamic routing, message durability, explicit delivery acknowledgments, and fine-grained backpressure controls.

---

## 1. The AMQP 0-9-1 Mental Model

In AMQP, **producers never publish messages directly into a queue**. Instead, messages flow through a sequence of specialized abstractions:

```mermaid
flowchart LR
    Producer["Producer\n(Service A)"] -->|"Publish with Routing Key:\ntask.work"| Exchange["Exchange\n(sandbox.direct)"]
    
    Exchange -->|"Binding Key: task.work"| MainQueue[("Work Queue\nsandbox.tasks.work")]
    Exchange -->|"Binding Key: task.audit"| AuditQueue[("Audit Queue\nsandbox.tasks.audit")]

    MainQueue -->|"Deliver Message"| Consumer1["Consumer Worker 1\n(Service B Node 1)"]
    MainQueue -->|"Deliver Message"| Consumer2["Consumer Worker 2\n(Service B Node 2)"]

    %% Distinct Theme Styling
    style Producer fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style Exchange fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style MainQueue fill:#1e293b,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style AuditQueue fill:#1e293b,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style Consumer1 fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style Consumer2 fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
```

### The Core AMQP Entities:

1. **Producer:** An application (Service A) that publishes messages to an exchange.
2. **Exchange:** An in-broker message router. It receives messages from producers and determines which queues should receive a copy based on predefined rules (**Bindings**).
3. **Binding:** A configuration link that connects an exchange to a queue (e.g. *"Route messages with routing key `task.work` to the queue `sandbox.tasks.work`"*).
4. **Routing Key:** A metadata string attached to every published message by the producer (like an envelope address).
5. **Queue:** A first-in, first-out (FIFO) storage buffer that holds messages in memory or on disk until consumers acknowledge them.
6. **Consumer:** A worker service (Service B) that subscribes to a queue, receives messages, executes the requested task, and sends an acknowledgment back.

---

## 2. The 4 Types of AMQP Exchanges

The Exchange type determines **how** the broker matches routing keys to queue bindings:

```mermaid
flowchart TD
    subgraph DirectEx ["1. Direct Exchange (Exact Match)"]
        direction LR
        D_Msg["Msg (key='work')"] --> D_Ex["Direct Exchange"]
        D_Ex -->|"Binding: 'work'"| D_Q1["Work Queue"]
        D_Ex -.->|"Binding: 'logs'"| D_Q2["Log Queue (Ignored)"]
    end

    subgraph FanoutEx ["2. Fanout Exchange (Broadcast All)"]
        direction LR
        F_Msg["Msg (any key)"] --> F_Ex["Fanout Exchange"]
        F_Ex -->|"Broadcast"| F_Q1["Worker Queue 1"]
        F_Ex -->|"Broadcast"| F_Q2["Worker Queue 2"]
    end

    subgraph TopicEx ["3. Topic Exchange (Wildcard Match)"]
        direction LR
        T_Msg["Msg (key='order.eu.created')"] --> T_Ex["Topic Exchange"]
        T_Ex -->|"Binding: 'order.eu.*'"| T_Q1["EU Orders Queue"]
        T_Ex -->|"Binding: 'order.#'"| T_Q2["All Orders Queue"]
    end

    subgraph HeadersEx ["4. Headers Exchange (Header Attributes Match)"]
        direction LR
        H_Msg["Msg (headers: format='pdf', type='report')"] --> H_Ex["Headers Exchange"]
        H_Ex -->|"Binding: format='pdf', type='report'<br/>(x-match='all')"| H_Q1["PDF Reports Queue"]
        H_Ex -.->|"Binding: format='zip'<br/>(x-match='all')"| H_Q2["ZIP Queue (Ignored)"]
    end

    DirectEx ~~~ FanoutEx ~~~ TopicEx ~~~ HeadersEx

    %% High-Contrast Subgraph Styling
    style DirectEx fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style FanoutEx fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style TopicEx fill:#4c1d95,stroke:#8b5cf6,stroke-width:2px,color:#ffffff
    style HeadersEx fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
```

### Summary of Exchange Types:

| Exchange Type | Routing Logic | Typical Use Case |
| :--- | :--- | :--- |
| **Direct** | Exact string match between Routing Key and Binding Key. | **Task / Work Queues (Used in our Sandbox)**. Point-to-point worker dispatch. |
| **Fanout** | Ignores routing keys completely. Clones message to **all bound queues**. | Pub/Sub notifications, real-time analytics feeds, cache invalidation broadcast. |
| **Topic** | Matches routing keys using wildcard patterns (`*` matches 1 word; `#` matches 0 or more words). | Regional routing (e.g. `sensors.us-east.temperature`), multi-tenant feeds. |
| **Headers** | Routes based on message header key-value attributes instead of routing keys. | Complex routing where headers contain routing metadata. |

---

## 3. The Message Acknowledgment Lifecycle

In synchronous HTTP, delivery confirmation happens implicitly when the TCP socket closes. In asynchronous systems, **workers can crash midway through a task**. 

RabbitMQ solves this with explicit **Delivery Acknowledgments (ACK / NACK)**:

```mermaid
flowchart TD
    MsgIn[("Message in Queue:\nState = READY")] -->|"Delivered to Worker"| InFlight["State = UNACKNOWLEDGED\n(Held in worker buffer)"]
    
    InFlight --> WorkerResult{"Worker Execution Outcome"}

    WorkerResult -->|"Success: Task Completed"| SendAck["Send Basic.Ack"]
    SendAck --> MsgPurged["Message Permanently Deleted from Queue"]

    WorkerResult -->|"Transient Failure\n(e.g. Database blip)"| SendNackRequeue["Send Basic.Nack(requeue=True)"]
    SendNackRequeue --> MsgRequeued["Message Returned to Queue Head for Another Worker"]

    WorkerResult -->|"Fatal Failure / Poison Pill\n(Invalid data / repeated crash)"| SendNackReject["Send Basic.Nack(requeue=False)"]
    SendNackReject --> RouteDLX{"Is Dead Letter Exchange (DLX) Configured?"}
    
    RouteDLX -->|"YES"| DLQ[("Routed to Dead Letter Queue (DLQ)\nfor Inspection")]
    RouteDLX -->|"NO"| Dropped["Message Discarded Permanently"]

    %% Semantic Styling
    style SendAck fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style MsgPurged fill:#047857,stroke:#34d399,stroke-width:2px,color:#ffffff
    style SendNackRequeue fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style SendNackReject fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#ffffff
    style DLQ fill:#450a0a,stroke:#dc2626,stroke-width:2px,color:#ffffff
```

### The Three Critical Rules of Acknowledgments:
1. **Never use auto-ack (`no_ack=True` / `auto_ack=True`):**
   * If auto-ack is enabled, RabbitMQ deletes the message from the queue the instant it pushes it over the network socket. If the worker container gets killed by the OS (OOM) 1 millisecond later, **the message is lost forever**.
2. **Always send manual ACKs after the work is done:**
   * Only send `basic_ack()` when your function has fully completed its computation or database commit.
3. **Beware of `requeue=True`:**
   * If a message crashes because the payload has invalid JSON or a corrupt field, sending `nack(requeue=True)` puts it right back at the top of the queue. The worker picks it up and crashes again immediately, creating an **infinite CPU-pegged crash loop**.

---

## 4. Backpressure & Consumer Prefetch (`prefetch_count`)

What happens when a producer dumps 10,000 tasks into RabbitMQ?

### Without Prefetch (The Default Trap):
* By default, RabbitMQ attempts to push **all 10,000 messages** into the connected consumer as fast as the network allows.
* The consumer's Python process buffers all 10,000 messages in process memory (`RAM`), triggering:
  * Extreme memory consumption.
  * Starvation of other worker nodes (one worker hoards all messages while other workers sit idle).

### With Prefetch (`basic_qos(prefetch_count=N)`):
* **`prefetch_count`** tells RabbitMQ: *"Do not send me more than $N$ unacknowledged messages at any given time."*
* If you set `prefetch_count = 5`:
  * RabbitMQ sends 5 tasks to the worker.
  * RabbitMQ **pauses** and holds the remaining 9,995 tasks in the broker queue.
  * Only when the worker completes Task #1 and sends `basic_ack()` does RabbitMQ dispatch Task #6.

```mermaid
flowchart LR
    Queue[("RabbitMQ Queue\n(10,000 Messages)")] -->|"Flow Controlled: Max 5 In-Flight"| Worker["Worker Node\n(prefetch_count = 5)"]
    Worker -->|"1. ACK Task 1"| Queue
    Queue -->|"2. Dispatch Task 6"| Worker

    style Queue fill:#1e293b,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style Worker fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
```

> **Direct Connection to PRD Requirement FR-3.2:**  
> Setting `prefetch_count` is the exact mechanism that enables **Controlled Concurrency**. It allows us to mathematically limit worker load regardless of how huge the incoming traffic spike is.

---

## 5. Summary & Checklist for Milestone 3

- [x] Configure a **Direct Exchange** (`sandbox.exchange`) bound to the work queue.
- [x] Mark queues and messages as **Durable** (`durable=True`, `delivery_mode=PERSISTENT`).
- [x] Use **manual message acknowledgments**; never enable automatic ACKs.
- [x] Configure channel **`prefetch_count`** (e.g. 5) to enforce consumer backpressure.
- [x] Catch fatal task errors and reject with `requeue=False` to trigger DLQ routing.

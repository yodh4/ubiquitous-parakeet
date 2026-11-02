# Conceptual Guide: Broker Infrastructure & Connection Mechanics

When working with message brokers like **RabbitMQ** for the first time, developers who are used to standard HTTP/REST microservices encounter several structural differences.

This guide explains the core concepts behind **broker port segregation**, **environment-aware connection strings**, and **role-tailored service configuration** as implemented in Step 1 of Milestone 3.

---

## 1. Segregation of Concerns: Data Plane vs. Control Plane

In traditional REST architectures, services use the exact same HTTP port for both business traffic and administrative endpoints (e.g. `POST /users` and `GET /health` both run on port `8080`).

Message brokers operate differently. RabbitMQ strictly separates the **Data Plane** (where application payloads travel) from the **Control Plane** (where humans inspect and manage broker state) across two completely different ports:

```mermaid
flowchart TD
    subgraph DataPlane ["1. The Data Plane (AMQP Port 5672)"]
        SvcA["Service A (Producer)"] -->|"AMQP Frames: Publish"| Port5672[("Port 5672\n(Host 5673)")]
        Port5672 -->|"AMQP Frames: Consume"| SvcB["Service B (Consumer)"]
    end

    subgraph ControlPlane ["2. The Control Plane (HTTP Port 15672)"]
        Operator(["Developer / Admin"]) -->|"HTTP / REST / Web UI"| Port15672[("Port 15672\n(Host 15673)")]
    end

    DataPlane ~~~ ControlPlane

    %% Distinct Styling adhering to DOCUMENTATION_RULES.md
    style DataPlane fill:#1e3a8a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style ControlPlane fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style SvcA fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style SvcB fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style Port5672 fill:#1e293b,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style Port15672 fill:#451a03,stroke:#fbbf24,stroke-width:2px,color:#ffffff
    style Operator fill:#334155,stroke:#94a3b8,stroke-width:2px,color:#ffffff
```

### The Data Plane (`Port 5672`, mapped to Host `5673`):
* **Protocol:** AMQP 0-9-1 (Advanced Message Queuing Protocol).
* **Wire Format:** Persistent binary frames over raw TCP.
* **Characteristics:** Extremely high throughput, sub-millisecond overhead, and binary serialization. This is the pipeline that Python's `aio-pika` driver speaks.
* **Why not HTTP?** Opening and closing HTTP request-response headers (`Content-Type`, `User-Agent`, cookies) adds massive byte bloat and round-trip latency. AMQP keeps a long-lived multiplexed TCP socket open, allowing tens of thousands of messages per second with minimal CPU consumption.

### The Control Plane (`Port 15672`, mapped to Host `15673`):
* **Protocol:** Standard HTTP / JSON.
* **Consumer:** The human engineer or an operations monitoring dashboard (Prometheus, Datadog).
* **Characteristics:** RabbitMQ embeds an HTTP management web server. Opening `http://localhost:15673` in a web browser renders an administrative dashboard displaying active connections, queue memory usage, consumer counts, and live message throughput graphs.

---

## 2. Dynamic Container Orchestration: Docker Profiles

In `docker-compose.yml`, the RabbitMQ container is defined with:
```yaml
profiles:
  - with-broker
```

### The Concept Behind Compose Profiles
A well-architected sandbox should allow developers to run different architectural stages without wasting system resources:
* **In Milestones 1 & 2 (Synchronous RPC):** The learner only tests timeouts, retries, and circuit breakers between Service A and Service B. Running a full message broker and Erlang VM in the background would consume unnecessary CPU and RAM. Because `rabbitmq` is assigned the `with-broker` profile, running `docker compose up` starts *only* Service A and Service B.
* **In Milestone 3 (Asynchronous Decoupling):** We explicitly request the broker profile:
  ```bash
  docker compose --profile with-broker up -d rabbitmq
  ```
  This tells Docker Compose to activate the optional container on demand.

---

## 3. The AMQP Connection URI Specification

Just as web browsers use `http://user:pass@host:port/path`, the AMQP specification defines a standardized connection URI syntax:

$$\text{amqp://}\underbrace{\text{guest:guest}}_{\text{Credentials}}\text{@}\underbrace{\text{hostname:port}}_{\text{Network Host}}\text{/}\underbrace{\text{vhost}}_{\text{Virtual Host}}$$

```mermaid
flowchart TD
    URI["amqp://guest:guest@localhost:5673/"]
    
    URI --> C1["Protocol: amqp://\n(Binary TCP Protocol)"]
    URI --> C2["Auth: guest:guest\n(Default Username & Password)"]
    URI --> C3["Network Address: localhost:5673\n(Host & AMQP Port)"]
    URI --> C4["Virtual Host: /\n(Isolated Broker Namespace)"]

    style URI fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style C1 fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style C2 fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style C3 fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style C4 fill:#4c1d95,stroke:#8b5cf6,stroke-width:2px,color:#ffffff
```

### What is a Virtual Host (vhost)?
A **Virtual Host** in RabbitMQ provides logical multitenancy inside a single broker cluster—identical to having multiple separate databases inside a single PostgreSQL server.
* Each vhost contains its own isolated set of exchanges, queues, and permissions.
* The default vhost is named `"/"` (a single forward slash).
* When building production systems, teams isolate environments using vhosts (e.g., `/dev`, `/staging`, `/prod`) on the same physical broker.

---

## 4. The Bridge: Host Networking vs. Docker Bridge Networking

A frequent source of configuration bugs in distributed systems is network locality. Where a service runs dictates where it must look for the broker:

```mermaid
flowchart TD
    subgraph HostEnv ["Scenario A: Local Development (Terminal CLI)"]
        LocalSvc["Local Python Service\n(uv run uvicorn)"] -->|"Connects to localhost:5673"| HostPort["Host Port 5673"]
        HostPort -->|"Port Forwarded"| ContainerA["RabbitMQ Container"]
    end

    subgraph DockerEnv ["Scenario B: Containerized Execution (Docker Compose)"]
        DockerSvc["Service Container\n(service-a:8000)"] -->|"Direct DNS: rabbitmq:5672"| ContainerB["RabbitMQ Container"]
    end

    HostEnv ~~~ DockerEnv

    style HostEnv fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#ffffff
    style DockerEnv fill:#022c22,stroke:#10b981,stroke-width:2px,color:#ffffff
    style LocalSvc fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style HostPort fill:#4c1d95,stroke:#8b5cf6,stroke-width:2px,color:#ffffff
    style ContainerA fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
    style DockerSvc fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#ffffff
    style ContainerB fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#ffffff
```

1. **Inside Docker (`docker-compose.yml`):**
   * Services share a user-defined bridge network (`sandbox-net`).
   * Docker provides internal DNS. Containers address each other by their container service name: `rabbitmq`.
   * They connect directly to the standard internal AMQP port: `5672`.
   * **URI:** `amqp://guest:guest@rabbitmq:5672/`
2. **On the Host Machine (`app/config.py` default):**
   * If you run `PYTHONPATH=services/service-a uvicorn ...` on your host terminal, the host machine does not resolve internal Docker DNS names like `rabbitmq`.
   * It must connect to `localhost` on the mapped external port: `5673`.
   * **URI:** `amqp://guest:guest@localhost:5673/`

By configuring `rabbitmq_url` via `pydantic-settings`, the code defaults to the local development URI, while Docker Compose injects `SERVICE_A_RABBITMQ_URL` and `SERVICE_B_RABBITMQ_URL` dynamically when deployed in containers.

---

## 5. Architectural Asymmetry: Producer Settings vs. Consumer Settings

In Step 1, you noticed that Service A and Service B were given completely different configuration variables:

| Setting Key | Assigned Service | Architectural Role | Why the other service does NOT have it |
| :--- | :--- | :--- | :--- |
| **`rabbitmq_exchange_name`** | **Service A** | Where Service A publishes outgoing tasks. | Service B does not publish; it consumes from a queue. |
| **`rabbitmq_routing_key`** | **Service A** | The routing label Service A attaches to messages. | Consumers subscribe to queues, not routing keys directly. |
| **`rabbitmq_queue_name`** | **Service B** | The FIFO queue buffer Service B consumes from. | **Decoupling:** Service A should not know where or how messages are stored. |
| **`rabbitmq_prefetch_count`** | **Service B** | Backpressure control (limits concurrent active tasks). | Service A is a producer; prefetch is a consumer-only concept. |
| **`rabbitmq_dlx_name`** | **Service B** | Dead Letter Exchange for rejected poison tasks. | Service A is unaware of task processing failures. |
| **`rabbitmq_dlq_name`** | **Service B** | Dead Letter Queue holding quarantined poison tasks. | Service A is unaware of task quarantine. |

### The Core Design Principle: Loose Spatial Coupling
If Service A knew the name of Service B's queue (`sandbox.tasks.work`), the two services would be **tightly coupled**.

By limiting Service A's knowledge strictly to an exchange name (`sandbox.exchange`) and a routing key (`task.work`), the architecture gains extreme flexibility:
1. We can attach an audit logger queue to `sandbox.exchange` tomorrow without modifying a single line of Service A's configuration.
2. We can swap Service B's queue buffering mechanism without Service A ever knowing.
3. The producer is solely responsible for **publishing events**, while the consumer is solely responsible for **task ingestion, backpressure, and failure quarantine**.

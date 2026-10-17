# Product Requirements Document (PRD)

**Project Name:** Zero-Logic Microservices Architecture Sandbox

**Status:** Draft

**Objective:** Educational / System Design & Distributed Architecture Mastery

---

## 1. Executive Summary

The **Zero-Logic Microservices Sandbox** is a minimalist, two-service distributed system designed strictly to explore, test, and observe microservices architecture and system design principles. By stripping away domain-specific business logic, database schemas, and user interfaces, the system isolates the core mechanics of distributed computing: inter-service communication, fault tolerance, asynchronous decoupling, horizontal scaling, and end-to-end observability.

---

## 2. Problem Statement

Learning microservices and system design often gets bogged down by complex business requirements (authentication, CRUD operations, data modeling, UI building). Beginners end up spending 80% of their time debugging application logic and only 20% learning architectural trade-offs.

There is a need for a pure, distraction-free architectural testbed where services act strictly as network nodes that receive requests, simulate configurable work or failure modes, and pass messages downstream.

---

## 3. Goals & Objectives

1. **Understand Coupling & Latency:** Observe the behavioral differences between synchronous (blocking) and asynchronous (non-blocking) service communication.
2. **Design for Failure:** Experience how downstream slowdowns or crashes trigger cascading failures, and verify how resilience patterns protect system stability.
3. **Handle High Throughput & Consistency Trade-offs:** Demonstrate load leveling under traffic spikes and solve duplicate message delivery (idempotency).
4. **Master System Visibility & Scaling:** Route traffic through a single entry point, scale worker nodes horizontally, and trace a single request across service boundaries.

---

## 4. Non-Goals (Out of Scope)

* **No Business Logic:** No real-world domain calculations, user accounts, or business workflows.
* **No Complex Data Persistence:** No relational schemas, migrations, or multi-table queries.
* **No Frontend / UI:** Interaction is strictly via API clients, load generators, and observability dashboards.
* **No Production Security:** No OAuth, RBAC, or user authentication flows.

---

## 5. System Actors & Components

* **External Client:** The initiator sending single requests or burst traffic into the system.
* **Edge Gateway:** The single entry point routing external requests to internal services.
* **Service A (Ingress / Producer):** Accepts incoming requests, attaches metadata (unique identifiers, timestamps), and coordinates downstream execution.
* **Service B (Worker / Consumer):** Receives tasks from Service A, executes simulated work (configurable artificial delay) or simulated failures (configurable error rates), and records completion.
* **Message Broker (Stage 3+):** An intermediary buffer holding events between Service A and Service B for asynchronous processing.

---

## 6. Functional Requirements (By Milestone)

### Milestone 1: Synchronous Baseline & Fault Injection

* **FR-1.1 (Request Triggering):** Service A must expose an endpoint that accepts a trigger request, generates a unique request ID, and synchronously calls Service B.
* **FR-1.2 (Workload Simulation):** Service B must accept parameters or configuration rules that dynamically control:
* **Artificial Latency:** How long Service B waits before responding (e.g., 50ms to 10,000ms).
* **Failure Rate:** A percentage chance (0% to 100%) that Service B immediately returns an error or drops the connection.


* **FR-1.3 (End-to-End Response):** Service A must return the combined result and total round-trip duration to the External Client.

### Milestone 2: Resilience & Self-Protection

* **FR-2.1 (Strict Timeouts):** Service A must enforce a maximum wait time when calling Service B and abort the request if the threshold is exceeded.
* **FR-2.2 (Automated Retries):** Upon transient failure from Service B, Service A must automatically retry the request using a controlled backoff schedule with randomized delay (jitter) to prevent synchronized retry storms.
* **FR-2.3 (Circuit Breaking):** When Service B exceeds a defined failure threshold over a rolling window, Service A must stop making network calls to Service B for a cool-down period and immediately return a graceful degraded response to the client.

### Milestone 3: Asynchronous Decoupling & Reliability

* **FR-3.1 (Non-Blocking Ingestion):** Service A must publish incoming tasks as events to a message broker and immediately return an acceptance acknowledgment (`Accepted` status) to the client without waiting for Service B.
* **FR-3.2 (Background Consumption):** Service B must independently pull and process tasks from the message broker at its own controlled concurrency rate.
* **FR-3.3 (Idempotent Processing):** Service B must detect and safely ignore duplicate deliveries of the same request ID so that a single task is never processed more than once.
* **FR-3.4 (Unprocessable Message Handling):** Tasks that repeatedly fail processing in Service B after maximum retries must be routed to an isolated Dead Letter Queue (DLQ) for inspection rather than blocking the main queue or being silently dropped.

### Milestone 4: Scaling, Routing & Observability

* **FR-4.1 (Single Entry Point):** All client traffic must enter through an Edge Gateway rather than addressing Service A or Service B directly.
* **FR-4.2 (Horizontal Scaling & Load Distribution):** The system must support running multiple identical instances of Service A and Service B simultaneously, distributing incoming requests and queued messages evenly across active instances.
* **FR-4.3 (Correlation & Distributed Tracing):** Every request entering the Edge Gateway must be assigned a Correlation/Trace ID that is propagated across Service A, the Message Broker, and Service B.
* **FR-4.4 (Centralized Telemetry):** Both services must emit structured logs and performance metrics (request rate, error rate, and latency percentiles) tagged with the Correlation ID.

---

## 7. Non-Functional Requirements & Acceptance Criteria

| Category | Requirement | Acceptance / Verification Scenario |
| --- | --- | --- |
| **Fault Isolation** | Service A must remain responsive even when Service B is completely unresponsive. | Set Service B latency to `10s` or failure rate to `100%`. Verify Service A trips its circuit breaker and responds to the client in less than `50ms` with a fallback message. |
| **Load Leveling** | Traffic spikes must not crash or overload Service B in asynchronous mode. | Send a burst of `500 requests` in 1 second to Service A while Service B is configured to process only `10 requests/sec`. Verify 0% error rate at Service A and steady backlog draining in Service B. |
| **Exactly-Once Effect** | Duplicate network messages must not result in duplicate work. | Publish the exact same `request_id` 5 times to the broker. Verify Service B executes the simulated work once and skips the remaining 4 attempts. |
| **Zero-Downtime Scaling** | Scaling worker instances up or down must not drop active requests. | Run a continuous load test while scaling Service B from 1 instance to 3 instances, then down to 2. Verify all accepted requests are accounted for. |
| **Traceability** | Any request's lifecycle must be reconstructable from start to finish. | Query a single `Correlation-ID` and view the exact timestamped path across the Gateway, Service A, any retries/queues, and Service B. |

---

## 8. Success Metrics (Learning Outcomes)

The project is considered complete when the builder can empirically demonstrate and measure:

1. **Tail Latency Amplification:** Showing how p99 latency in Service B directly degrades Service A in Stage 1, and how Stage 2/3 mitigate it.
2. **Recovery Time Objective (RTO):** Measuring how quickly the system recovers automatically once Service B is restored from a simulated outage.
3. **Throughput vs. Latency Curve:** Comparing maximum requests per second (RPS) and client wait time between the synchronous architecture and the asynchronous architecture.

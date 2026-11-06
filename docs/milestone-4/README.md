# Milestone 4: Scaling, Routing & Observability

Welcome to **Milestone 4**, the capstone milestone of the Zero-Logic Microservices Architecture Sandbox.

Having established synchronous resilience (Timeouts, Retries, Circuit Breaker in Milestones 1 & 2) and asynchronous decoupling (RabbitMQ queues, load leveling, idempotency, and DLQ in Milestone 3), Milestone 4 transforms the sandbox into a **production-ready distributed cluster**.

---

## 🎯 Educational Goal

To master how distributed systems maintain **visibility**, **balance load**, and **scale out** when traffic increases and multiple service replicas run concurrently:
1. How does an operator trace a single transaction that touches multiple machines, network hops, and asynchronous message brokers?
2. How do machine-readable structured logs replace fragile plain-text console logging?
3. Why must an Edge Gateway shield internal microservice topologies from external clients?
4. How do multiple worker replicas coordinate and share work without stepping on each other?

---

## 🗺️ Progressive Phase Structure

To prevent cognitive overload from learning multiple infrastructure technologies at once, Milestone 4 is split into **4 concept-isolated phases**:

| Phase | Core Concept & Real-World Metaphor | Primary Technology |
| :--- | :--- | :--- |
| **[Phase 1](IMPLEMENTATION_PLAN.md#phase-1-distributed-correlation-id-the-fedex-tracking-number)** | **Distributed Correlation ID:** The *"FedEx Tracking Number"* stamped on every request across HTTP and AMQP. | Pure Python: FastAPI Middleware + `aio-pika` message headers |
| **[Phase 2](IMPLEMENTATION_PLAN.md#phase-2-structured-json-logging-machine-readable-telemetry)** | **Structured JSON Logging:** Replacing free-form text with searchable machine-readable logs tagged with the Correlation ID. | Python `logging` + JSON Formatter |
| **[Phase 3](IMPLEMENTATION_PLAN.md#phase-3-the-edge-gateway-the-front-door-receptionist)** | **The Edge Gateway / Reverse Proxy:** The single ingress front door routing traffic and injecting IDs. | Lightweight Reverse Proxy (Traefik / Nginx) |
| **[Phase 4](IMPLEMENTATION_PLAN.md#phase-4-horizontal-scaling--load-distribution-more-cashiers)** | **Horizontal Scaling & Load Distribution:** Adding worker replicas and observing Round-Robin & Competing Consumers. | Docker Compose (`--scale`) + Gateway Load Balancing |

---

## 📚 Milestone 4 Documentation Index

* **[Implementation Plan & Step-by-Step Roadmap](IMPLEMENTATION_PLAN.md)**
* **[Phase 1 Inquiry: Distributed Correlation ID & End-to-End Tracing](qa-phase-1-correlation-id.md)**
* Additional inquiry and verification logs will be recorded as each phase is completed.

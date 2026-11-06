# Zero-Logic Microservices Architecture Sandbox

A minimalist, two-service distributed system designed strictly to explore, test, and observe microservices architecture and system design principles without business logic distractions.

> 📖 **Architecture & Diagrams:**  
> - [System Architecture & Component Overview](docs/ARCHITECTURE_OVERVIEW.md)  
> - [C4 Level 2: Container Diagram](docs/c4-container-diagram.md)  
> - [C4 Level 3: Component Diagram](docs/c4-component-diagram.md)  
> - [Synchronous gRPC vs. Asynchronous Message Broker](docs/synchronous-grpc-vs-asynchronous-message-broker.md)

## Project Structure

```text
.
├── prd.md                    # Product Requirements Document
├── docker-compose.yml        # Multi-container orchestration (Service A, B, RabbitMQ)
├── pyproject.toml            # Root workspace definition
├── services/
│   ├── service-a/            # Ingress / Producer (FastAPI)
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   └── app/
│   │       ├── __init__.py
│   │       ├── config.py
│   │       ├── main.py
│   │       └── schemas.py
│   └── service-b/            # Worker / Consumer (FastAPI)
│       ├── Dockerfile
│       ├── pyproject.toml
│       ├── uv.lock
│       └── app/
│           ├── __init__.py
│           ├── config.py
│           ├── main.py
│           └── schemas.py
└── scripts/                  # Load testing and fault injection verification scripts
```

## Quick Start

### 1. Run with Docker Compose
```bash
docker compose up --build
```
* **Service A:** http://localhost:8000 (Docs: http://localhost:8000/docs)
* **Service B:** http://localhost:8001 (Docs: http://localhost:8001/docs)

### 2. Run Locally (Development)
```bash
# Sync workspace environment
uv sync

# Run Service B (Port 8001)
PYTHONPATH=services/service-b uvicorn app.main:app --port 8001 --reload

# Run Service A (Port 8000)
PYTHONPATH=services/service-a uvicorn app.main:app --port 8000 --reload
```

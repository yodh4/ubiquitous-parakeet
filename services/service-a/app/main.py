from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.config import settings
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup shared httpx.AsyncClient with connection pooling
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_seconds)
    )
    yield
    # Clean up client on shutdown
    await app.state.http_client.aclose()


app = FastAPI(
    title="Service A (Ingress / Producer)",
    description="Accepts incoming requests and coordinates downstream execution.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(service=settings.service_name)

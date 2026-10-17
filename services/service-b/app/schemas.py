from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "service-b"


class WorkRequest(BaseModel):
    request_id: str = Field(..., description="Unique correlation / request identifier")
    latency_ms: int = Field(default=0, ge=0, le=60000, description="Artificial latency in milliseconds")
    failure_rate_pct: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Chance of simulated failure (0.0% to 100.0%)"
    )


class WorkResponse(BaseModel):
    request_id: str
    status: str = "completed"
    service: str = "service-b"
    hostname: str
    simulated_latency_ms: int
    completed_at: datetime

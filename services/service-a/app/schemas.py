from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "service-a"


class TriggerRequest(BaseModel):
    latency_ms: int = Field(default=0, ge=0, le=60000, description="Downstream simulated latency in milliseconds")
    failure_rate_pct: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Downstream simulated failure rate (0.0% to 100.0%)"
    )


class TriggerResponse(BaseModel):
    request_id: str
    status: str
    round_trip_duration_ms: float
    service_a_timestamp: datetime
    downstream: dict[str, Any] | None = None
    error: dict[str, Any] | str | None = None

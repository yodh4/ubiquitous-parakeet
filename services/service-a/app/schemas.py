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
    timeout_ms: int | None = Field(
        default=None, ge=1, le=60000, description="Strict per-attempt timeout in ms. Defaults to service config."
    )
    max_retries: int | None = Field(
        default=None, ge=0, le=10, description="Maximum retry attempts on transient failure. Defaults to service config."
    )
    use_circuit_breaker: bool = Field(default=True, description="Whether to route through the Circuit Breaker.")
    use_retry: bool = Field(default=True, description="Whether to enable automated retries.")
    use_jitter: bool = Field(default=True, description="Whether to apply Full Jitter to retry backoff.")


class ResilienceMetadata(BaseModel):
    circuit_breaker_state: str
    attempts: int
    retry_delays_ms: list[float]
    timeout_enforced_ms: float
    circuit_breaker_tripped: bool = False
    cooldown_remaining_seconds: float | None = None


class TriggerResponse(BaseModel):
    request_id: str
    status: str
    round_trip_duration_ms: float
    service_a_timestamp: datetime
    downstream: dict[str, Any] | None = None
    error: dict[str, Any] | str | None = None
    resilience: ResilienceMetadata | None = None


class CircuitBreakerStatusResponse(BaseModel):
    state: str
    failure_count: int
    failure_threshold: int
    recovery_timeout_seconds: float
    cooldown_remaining_seconds: float
    last_state_change_utc: str
    last_failure_reason: str | None = None


class CircuitBreakerResetResponse(BaseModel):
    status: str = "reset"
    circuit_breaker: CircuitBreakerStatusResponse

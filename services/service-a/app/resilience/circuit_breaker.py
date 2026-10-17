import asyncio
import logging
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger("service-a.circuit-breaker")


class BreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    def __init__(self, message: str, cooldown_remaining_seconds: float, last_failure_reason: str | None = None):
        super().__init__(message)
        self.message = message
        self.cooldown_remaining_seconds = cooldown_remaining_seconds
        self.last_failure_reason = last_failure_reason


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 5.0,
        half_open_max_probes: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_max_probes = half_open_max_probes

        self.state: BreakerState = BreakerState.CLOSED
        self.failure_count: int = 0
        self.success_count: int = 0
        self.last_state_change: float = time.monotonic()
        self.last_state_change_utc: datetime = datetime.now(UTC)
        self.last_failure_reason: str | None = None
        self._half_open_in_flight: int = 0

        self._lock = asyncio.Lock()

    async def acquire_permission(self) -> None:
        """Checks if a request is allowed to proceed downstream.
        
        Raises:
            CircuitBreakerOpenException: If the circuit is OPEN or probe capacity is full.
        """
        async with self._lock:
            now = time.monotonic()

            if self.state == BreakerState.CLOSED:
                return

            if self.state == BreakerState.OPEN:
                elapsed = now - self.last_state_change
                if elapsed >= self.recovery_timeout_seconds:
                    logger.info("CircuitBreaker cooldown expired (%.2fs >= %.2fs). Transitioning OPEN -> HALF_OPEN",
                                elapsed, self.recovery_timeout_seconds)
                    self.state = BreakerState.HALF_OPEN
                    self.last_state_change = now
                    self.last_state_change_utc = datetime.now(UTC)
                    self._half_open_in_flight = 1
                    return
                
                remaining = round(self.recovery_timeout_seconds - elapsed, 2)
                raise CircuitBreakerOpenException(
                    message=f"Circuit Breaker is OPEN. Cooldown remaining: {remaining}s",
                    cooldown_remaining_seconds=remaining,
                    last_failure_reason=self.last_failure_reason,
                )

            if self.state == BreakerState.HALF_OPEN:
                if self._half_open_in_flight < self.half_open_max_probes:
                    self._half_open_in_flight += 1
                    return
                raise CircuitBreakerOpenException(
                    message="Circuit Breaker is HALF-OPEN. Canary probe already in flight.",
                    cooldown_remaining_seconds=0.0,
                    last_failure_reason=self.last_failure_reason,
                )

    async def record_success(self) -> None:
        """Records a successful downstream call."""
        async with self._lock:
            self.success_count += 1
            if self.state == BreakerState.HALF_OPEN:
                logger.info("Canary probe succeeded! Transitioning HALF_OPEN -> CLOSED")
                self.state = BreakerState.CLOSED
                self.failure_count = 0
                self._half_open_in_flight = 0
                self.last_state_change = time.monotonic()
                self.last_state_change_utc = datetime.now(UTC)
            elif self.state == BreakerState.CLOSED:
                # Reset consecutive failure counter on healthy traffic
                self.failure_count = 0

    async def record_failure(self, reason: str = "Downstream failure") -> None:
        """Records a downstream failure and evaluates whether to trip."""
        async with self._lock:
            now = time.monotonic()
            self.last_failure_reason = reason

            if self.state == BreakerState.HALF_OPEN:
                logger.warning("Canary probe failed! Re-tripping HALF_OPEN -> OPEN. Reason: %s", reason)
                self.state = BreakerState.OPEN
                self.last_state_change = now
                self.last_state_change_utc = datetime.now(UTC)
                self._half_open_in_flight = 0
                return

            if self.state == BreakerState.CLOSED:
                self.failure_count += 1
                logger.warning("Downstream failure recorded (%d/%d): %s",
                               self.failure_count, self.failure_threshold, reason)
                if self.failure_count >= self.failure_threshold:
                    logger.error("Failure threshold reached! Tripping CLOSED -> OPEN.")
                    self.state = BreakerState.OPEN
                    self.last_state_change = now
                    self.last_state_change_utc = datetime.now(UTC)

    async def reset(self) -> None:
        """Manually resets the circuit breaker to CLOSED."""
        async with self._lock:
            self.state = BreakerState.CLOSED
            self.failure_count = 0
            self._half_open_in_flight = 0
            self.last_state_change = time.monotonic()
            self.last_state_change_utc = datetime.now(UTC)
            self.last_failure_reason = None
            logger.info("Circuit Breaker manually reset to CLOSED.")

    def get_status(self) -> dict[str, Any]:
        """Returns the real-time state of the breaker for telemetry and monitoring."""
        now = time.monotonic()
        cooldown_remaining = 0.0
        if self.state == BreakerState.OPEN:
            elapsed = now - self.last_state_change
            cooldown_remaining = max(0.0, round(self.recovery_timeout_seconds - elapsed, 2))

        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "cooldown_remaining_seconds": cooldown_remaining,
            "last_state_change_utc": self.last_state_change_utc.isoformat(),
            "last_failure_reason": self.last_failure_reason,
        }

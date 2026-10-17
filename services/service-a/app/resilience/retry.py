import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("service-a.retry")


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_ms: float = 50.0
    max_delay_ms: float = 1000.0
    jitter: bool = True
    retryable_status_codes: tuple[int, ...] = (500, 502, 503, 504)

    def calculate_delay_ms(self, attempt: int) -> float:
        """Calculates backoff delay with Full Jitter.
        
        Formula:
            exp_delay = min(max_delay_ms, base_delay_ms * (2 ** attempt))
            sleep_time = random.uniform(0, exp_delay) if jitter else exp_delay
        """
        exp_delay = min(self.max_delay_ms, self.base_delay_ms * (2 ** attempt))
        if self.jitter:
            return round(random.uniform(0.0, exp_delay), 2)
        return round(exp_delay, 2)


@dataclass
class RetryExecutionResult:
    response: httpx.Response | None
    attempts: int
    retry_delays_ms: list[float] = field(default_factory=list)
    last_exception: Exception | None = None


async def execute_with_retry(
    operation: Callable[[], Awaitable[httpx.Response]],
    policy: RetryPolicy,
    request_id: str = "unknown",
) -> RetryExecutionResult:
    """Executes an async network operation with retries, exponential backoff, and jitter.
    
    Args:
        operation: Async callable returning an httpx.Response.
        policy: The RetryPolicy to enforce.
        request_id: Correlation ID for logging.
    """
    retry_delays: list[float] = []
    total_attempts = policy.max_retries + 1

    for attempt in range(total_attempts):
        attempt_number = attempt + 1
        last_exception = None
        response = None

        try:
            response = await operation()

            # If response is successful, we are done!
            if response.status_code not in policy.retryable_status_codes:
                if attempt > 0:
                    logger.info("Request id=%s SUCCEEDED on attempt %d/%d after %d retries",
                                request_id, attempt_number, total_attempts, attempt)
                return RetryExecutionResult(
                    response=response,
                    attempts=attempt_number,
                    retry_delays_ms=retry_delays,
                )

            # Response is in retryable_status_codes (e.g. 500, 502, 503, 504)
            logger.warning(
                "Request id=%s attempt %d/%d returned retryable status %d",
                request_id, attempt_number, total_attempts, response.status_code,
            )

        except (httpx.TimeoutException, TimeoutError, httpx.ConnectError) as exc:
            last_exception = exc
            logger.warning(
                "Request id=%s attempt %d/%d failed with exception: %s",
                request_id, attempt_number, total_attempts, type(exc).__name__,
            )

        # Check if we have retries remaining
        if attempt < policy.max_retries:
            delay_ms = policy.calculate_delay_ms(attempt)
            retry_delays.append(delay_ms)
            logger.info("Request id=%s scheduling retry %d in %.2fms (jitter=%s)",
                        request_id, attempt + 1, delay_ms, policy.jitter)
            await asyncio.sleep(delay_ms / 1000.0)
        else:
            # All retries exhausted
            logger.error("Request id=%s exhausted all %d attempts", request_id, total_attempts)
            return RetryExecutionResult(
                response=response,
                attempts=attempt_number,
                retry_delays_ms=retry_delays,
                last_exception=last_exception,
            )

    return RetryExecutionResult(
        response=None,
        attempts=total_attempts,
        retry_delays_ms=retry_delays,
        last_exception=RuntimeError("Unexpected retry loop termination"),
    )

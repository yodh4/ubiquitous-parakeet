import asyncio
import logging
import time
from collections import OrderedDict

logger = logging.getLogger("service-b.idempotency")


class IdempotencyStore:
    """Thread-safe in-memory deduplication store with TTL expiration, bounded capacity,
    and in-flight concurrent execution suppression.
    
    Guarantees the Exactly-Once processing effect by detecting duplicate request IDs
    arising from:
      1. Concurrent redeliveries / burst duplicates (in-flight tracking).
      2. Subsequent redeliveries after task completion (TTL sliding window).
    """

    def __init__(self, default_ttl_seconds: int = 300, max_capacity: int = 10000):
        self.default_ttl_seconds = default_ttl_seconds
        self.max_capacity = max_capacity
        self._in_flight: set[str] = set()
        self._completed: OrderedDict[str, float] = OrderedDict()
        self._lock = asyncio.Lock()

    async def check_and_acquire(self, request_id: str) -> bool:
        """Atomically checks if a request_id is new, and if so, marks it IN-FLIGHT.
        
        Returns:
            True if this is a brand-new task and acquisition succeeded.
            False if this is a duplicate (either currently executing or already completed).
        """
        async with self._lock:
            now = time.monotonic()

            # 1. Check if currently executing in-flight by another concurrent worker task
            if request_id in self._in_flight:
                logger.debug("Request id=%s is already IN-FLIGHT. Duplicate suppressed.", request_id)
                return False

            # 2. Check if already completed previously within TTL window
            expires_at = self._completed.get(request_id)
            if expires_at is not None:
                if now <= expires_at:
                    self._completed.move_to_end(request_id)
                    logger.debug("Request id=%s was ALREADY COMPLETED. Duplicate suppressed.", request_id)
                    return False
                # Expired -> Clean up
                del self._completed[request_id]

            # 3. New task -> Acquire in-flight lease
            self._in_flight.add(request_id)
            return True

    async def mark_completed(self, request_id: str, ttl_seconds: int | None = None) -> None:
        """Transitions request_id from IN-FLIGHT to COMPLETED with a TTL expiration deadline."""
        async with self._lock:
            self._in_flight.discard(request_id)

            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
            now = time.monotonic()
            expires_at = now + ttl

            # Evict oldest entry if capacity limit reached
            if len(self._completed) >= self.max_capacity:
                oldest_key, _ = self._completed.popitem(last=False)
                logger.debug(
                    "IdempotencyStore capacity reached (%d). Evicted oldest key=%s",
                    self.max_capacity,
                    oldest_key,
                )

            self._completed[request_id] = expires_at
            self._completed.move_to_end(request_id)
            logger.debug("Marked request_id=%s as COMPLETED (TTL=%ds)", request_id, ttl)

    async def release_in_flight(self, request_id: str) -> None:
        """Releases the in-flight lease if task execution failed, allowing retries or DLQ handling."""
        async with self._lock:
            self._in_flight.discard(request_id)

    async def clear(self) -> None:
        """Clears all stored entries (useful for test resets)."""
        async with self._lock:
            self._in_flight.clear()
            self._completed.clear()

    async def size(self) -> int:
        """Returns the current number of active (non-expired) completed entries."""
        async with self._lock:
            now = time.monotonic()
            expired_keys = [k for k, exp in self._completed.items() if now > exp]
            for k in expired_keys:
                del self._completed[k]
            return len(self._completed)

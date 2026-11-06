import contextvars
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HEADER_NAME = "X-Correlation-ID"

_correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id",
    default=None,
)


def get_correlation_id() -> str | None:
    """Returns the correlation ID from the current async execution context."""
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> None:
    """Manually sets the correlation ID in the current async execution context."""
    _correlation_id_ctx.set(correlation_id)


@asynccontextmanager
async def correlation_scope(correlation_id: str | None = None) -> AsyncIterator[str]:
    """Async context manager that scopes a correlation ID to a block of code."""
    cid = correlation_id.strip() if correlation_id and correlation_id.strip() else uuid.uuid4().hex
    token = _correlation_id_ctx.set(cid)
    try:
        yield cid
    finally:
        _correlation_id_ctx.reset(token)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware that extracts or generates X-Correlation-ID.

    Guarantees that every request has a tracking ID bound to Python's contextvars
    and stamped on the outgoing HTTP response headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_cid = request.headers.get(HEADER_NAME) or request.headers.get(HEADER_NAME.lower())
        async with correlation_scope(incoming_cid) as cid:
            response: Response = await call_next(request)
            response.headers[HEADER_NAME] = cid
            return response

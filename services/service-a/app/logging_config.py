import json
import logging
import sys
from datetime import UTC, datetime

from app.correlation import get_correlation_id

# Standard LogRecord attributes that should not be dumped into extra JSON fields
STANDARD_LOG_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
    "correlation_id",
}


class CorrelationIdFilter(logging.Filter):
    """Injects the active correlation ID from contextvars into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JSONFormatter(logging.Formatter):
    """Serializes LogRecords into standardized, single-line JSON format."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }

        # Include custom extra fields if provided by logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_RECORD_ATTRS and not key.startswith("_"):
                log_entry[key] = value

        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Configures root and framework loggers to emit JSON to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(service_name=service_name))
    handler.addFilter(CorrelationIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for uvicorn_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        u_log = logging.getLogger(uvicorn_name)
        u_log.handlers.clear()
        u_log.addHandler(handler)
        u_log.propagate = False

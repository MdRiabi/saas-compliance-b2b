import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone


_request_id_context = ContextVar("request_id", default=None)
_REQUEST_FIELDS = (
    "event",
    "request_id",
    "http_method",
    "endpoint",
    "status_code",
    "duration_ms",
)


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = _request_id_context.get()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _REQUEST_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        return json.dumps(entry, ensure_ascii=True, separators=(",", ":"))


def set_request_id(request_id):
    return _request_id_context.set(request_id)


def reset_request_id(token):
    _request_id_context.reset(token)


def configure_app_logger(logger):
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonLogFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.propagate = False

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError


_request_id_context = ContextVar("request_id", default=None)
_REQUEST_FIELDS = (
    "event",
    "request_id",
    "action",
    "outcome",
    "operation",
    "error_category",
    "error_type",
    "error_code",
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
            "message": (
                record.getMessage()
                if hasattr(record, "event")
                else "Framework log event"
            ),
        }
        for field in _REQUEST_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        return json.dumps(entry, ensure_ascii=True, separators=(",", ":"))


def set_request_id(request_id):
    return _request_id_context.set(request_id)


def reset_request_id(token):
    _request_id_context.reset(token)


def log_authentication_event(logger, action, outcome):
    level = (
        logging.WARNING
        if outcome in {"failure", "denied"}
        else logging.INFO
    )
    logger.log(
        level,
        "Authentication event",
        extra={
            "event": "security.authentication",
            "action": action,
            "outcome": outcome,
        },
    )


def log_unhandled_exception(sender, exception):
    sender.logger.error(
        "Unhandled application exception",
        extra={
            "event": "application.exception",
            "error_category": (
                "database" if isinstance(exception, SQLAlchemyError) else "application"
            ),
            "error_type": type(exception).__name__,
        },
    )


def configure_app_logger(logger):
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonLogFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.propagate = False

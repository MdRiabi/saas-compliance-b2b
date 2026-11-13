import json
import logging
import sys
from datetime import datetime, timezone


_REQUEST_FIELDS = (
    "event",
    "http_method",
    "endpoint",
    "status_code",
    "duration_ms",
)


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


def configure_app_logger(logger):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.propagate = False

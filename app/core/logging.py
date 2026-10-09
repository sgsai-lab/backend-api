import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = frozenset(
    {"authorization", "cookie", "code", "otp", "recovery_code", "mfa_code", "id_token", "nonce"}
)
_SENSITIVE_FRAGMENTS = ("password", "token", "secret")


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_KEYS or any(f in lowered for f in _SENSITIVE_FRAGMENTS)


def redact_sensitive(_: Any, __: str, event_dict: EventDict) -> EventDict:
    for key in event_dict:
        if _is_sensitive(key):
            event_dict[key] = REDACTED
    return event_dict


def _to_cloud_severity(_: Any, __: str, event_dict: EventDict) -> EventDict:
    # Cloud Logging reads `severity` and `message` from JSON payloads.
    event_dict["severity"] = str(event_dict.pop("level", "info")).upper()
    return event_dict


def configure_logging(level: str, json_logs: bool) -> None:
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        redact_sensitive,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_logs:
        processors += [
            _to_cloud_severity,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

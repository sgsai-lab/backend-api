import re
from typing import Any

import pytest
import structlog
from fastapi import Request
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.logging import REDACTED, _to_cloud_severity, configure_logging, redact_sensitive
from app.core.middleware import _bind_trace


@pytest.mark.parametrize(
    "key",
    ["password", "new_password", "refresh_token", "Authorization", "code", "client_secret", "otp"],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    event: dict[str, Any] = {"event": "x", key: "super-secret"}

    result = redact_sensitive(None, "info", event)

    assert result[key] == REDACTED


def test_non_sensitive_keys_are_kept() -> None:
    event: dict[str, Any] = {"event": "x", "user_id": "u1", "status_code": 200}

    result = redact_sensitive(None, "info", event)

    assert result == {"event": "x", "user_id": "u1", "status_code": 200}


def test_cloud_severity_uppercases_level() -> None:
    assert _to_cloud_severity(None, "warning", {"level": "warning"})["severity"] == "WARNING"


def test_json_logging_emits_cloud_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)
    try:
        structlog.get_logger("t").info("hello", password="hunter2")
        output = capsys.readouterr().out
    finally:
        configure_logging("INFO", json_logs=False)

    assert '"severity": "INFO"' in output
    assert '"message": "hello"' in output
    assert "hunter2" not in output


def test_cloud_trace_is_bound_when_project_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "gcp_project_id", "demo-project")
    trace_id = "a" * 32
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-cloud-trace-context", f"{trace_id}/1;o=1".encode())],
        }
    )
    structlog.contextvars.clear_contextvars()

    _bind_trace(request)

    assert structlog.contextvars.get_contextvars()["logging.googleapis.com/trace"] == (
        f"projects/demo-project/traces/{trace_id}"
    )
    structlog.contextvars.clear_contextvars()


async def test_request_is_logged_with_status(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await client.get("/healthz")

    output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "path=/healthz" in output
    assert "status_code=200" in output

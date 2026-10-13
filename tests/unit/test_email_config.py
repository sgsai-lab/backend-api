import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core import email as email_module
from app.core.config import Settings, get_settings
from app.core.email import (
    SUBJECTS,
    ApiEmailSender,
    EmailMessage,
    InMemoryEmailSender,
    Mailer,
    SmtpEmailSender,
    render_email,
)


@pytest.mark.parametrize("template", sorted(SUBJECTS))
def test_every_template_renders_text_and_html(template: str) -> None:
    message = render_email(
        "a@example.com", template, {"name": "<Ada>", "link": "https://x/y?token=t", "minutes": 15}
    )

    assert message.subject == SUBJECTS[template]
    assert "<Ada>" in message.text
    assert "&lt;Ada&gt;" in message.html


async def test_mailer_builds_links_and_sends() -> None:
    sender = InMemoryEmailSender()
    mailer = Mailer(sender, get_settings())

    link = mailer.link("/reset-password", "a b&c")
    await mailer.send("a@example.com", "password_reset", name="Ada", link=link)

    assert link == "https://app.example.com/reset-password?token=a+b%26c"
    assert sender.outbox[0].to == "a@example.com"


async def test_mailer_swallows_provider_failures() -> None:
    class FailingSender:
        async def send(self, message: EmailMessage) -> None:
            raise ConnectionError("provider down")

    await Mailer(FailingSender(), get_settings()).send("a@example.com", "mfa_enabled", name="Ada")


async def test_smtp_sender_builds_multipart_message(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    async def fake_send(message: Any, **kwargs: Any) -> None:
        sent.update(message=message, **kwargs)

    monkeypatch.setattr("app.core.email.aiosmtplib.send", fake_send)
    settings = get_settings().model_copy(
        update={"smtp_username": "u", "smtp_password": SecretStr("p")}
    )

    await SmtpEmailSender(settings).send(
        render_email("a@example.com", "mfa_enabled", {"name": "A"})
    )

    assert sent["message"]["To"] == "a@example.com"
    assert sent["message"].is_multipart()
    assert sent["password"] == "p"


async def test_api_sender_posts_sendgrid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(202)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.core.email.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    settings = get_settings().model_copy(update={"email_api_key": SecretStr("sg-key")})

    await ApiEmailSender(settings).send(render_email("a@example.com", "mfa_enabled", {"name": "A"}))

    assert captured["auth"] == "Bearer sg-key"
    assert captured["body"]["personalizations"][0]["to"][0]["email"] == "a@example.com"
    assert captured["body"]["from"]["email"] == "no-reply@sgsai.local"


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("smtp", SmtpEmailSender), ("api", ApiEmailSender), ("memory", InMemoryEmailSender)],
)
def test_sender_selection(
    monkeypatch: pytest.MonkeyPatch, backend: str, expected: type[object]
) -> None:
    settings = get_settings().model_copy(update={"email_backend": backend})
    monkeypatch.setattr(email_module, "get_settings", lambda: settings)
    email_module.get_email_sender.cache_clear()
    try:
        assert isinstance(email_module.get_email_sender(), expected)
    finally:
        email_module.get_email_sender.cache_clear()


def test_production_requires_secrets() -> None:
    with pytest.raises(ValidationError, match="jwt_private_key"):
        Settings(environment="production", email_backend="api")


def test_production_accepts_complete_secrets() -> None:
    settings = Settings(
        environment="production",
        jwt_private_key=SecretStr("pem"),
        mfa_encryption_key=SecretStr("key"),
        firebase_project_id="sgsai-prod",
        email_backend="api",
        email_api_key=SecretStr("sg"),
    )

    assert settings.docs_enabled is False
    assert settings.allows_ephemeral_keys is False

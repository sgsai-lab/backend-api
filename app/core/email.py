import asyncio
from dataclasses import dataclass, field
from email.message import EmailMessage as MimeMessage
from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Protocol
from urllib.parse import urlencode

import aiosmtplib
import httpx
import structlog
from fastapi import Depends
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings, get_settings

log = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False),
    undefined=StrictUndefined,
)

SUBJECTS = {
    "verify_email": "Verify your email address",
    "signup_existing": "Sign-up attempt with your email address",
    "password_reset": "Reset your password",
    "password_changed": "Your password was changed",
    "mfa_enabled": "Two-factor authentication enabled",
    "mfa_disabled": "Two-factor authentication disabled",
    "account_locked": "Unusual sign-in activity on your account",
    "invite": "You have been invited to SGS AI",
}


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    template: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = self._settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        password = self._settings.smtp_password
        await aiosmtplib.send(
            mime,
            hostname=self._settings.smtp_host,
            port=self._settings.smtp_port,
            username=self._settings.smtp_username,
            password=password.get_secret_value() if password else None,
            start_tls=self._settings.smtp_start_tls,
            timeout=self._settings.email_timeout_seconds,
        )


class ApiEmailSender:
    """SendGrid v3 mail/send API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: EmailMessage) -> None:
        name, address = parseaddr(self._settings.email_from)
        api_key = self._settings.email_api_key
        payload = {
            "personalizations": [{"to": [{"email": message.to}]}],
            "from": {"email": address, "name": name},
            "subject": message.subject,
            "content": [
                {"type": "text/plain", "value": message.text},
                {"type": "text/html", "value": message.html},
            ],
        }
        async with httpx.AsyncClient(timeout=self._settings.email_timeout_seconds) as client:
            response = await client.post(
                self._settings.email_api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key.get_secret_value() if api_key else ''}"
                },
            )
            response.raise_for_status()


@dataclass
class InMemoryEmailSender:
    outbox: list[EmailMessage] = field(default_factory=list)

    async def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


def render_email(to: str, template: str, context: dict[str, Any]) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject=SUBJECTS[template],
        text=_env.get_template(f"{template}.txt.j2").render(**context),
        html=_env.get_template(f"{template}.html.j2").render(**context),
        template=template,
    )


class Mailer:
    def __init__(self, sender: EmailSender, settings: Settings) -> None:
        self._sender = sender
        self._settings = settings

    def link(self, path: str, token: str) -> str:
        return f"{self._settings.frontend_base_url.rstrip('/')}{path}?{urlencode({'token': token})}"

    async def send(self, to: str, template: str, **context: Any) -> None:
        message = render_email(to, template, context)
        try:
            async with asyncio.timeout(self._settings.email_timeout_seconds):
                await self._sender.send(message)
        except Exception as exc:
            # Email is best-effort: never fail the user request because the provider is down.
            log.warning("email_send_failed", template=template, exc_type=type(exc).__name__)
            return
        log.info("email_sent", template=template)


@lru_cache
def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.email_backend == "api":
        return ApiEmailSender(settings)
    if settings.email_backend == "memory":
        return InMemoryEmailSender()
    return SmtpEmailSender(settings)


def get_mailer(sender: Annotated[EmailSender, Depends(get_email_sender)]) -> Mailer:
    return Mailer(sender, get_settings())


MailerDep = Annotated[Mailer, Depends(get_mailer)]

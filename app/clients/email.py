from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

from app.core.config import Settings
from app.core.errors import EmailSendError


IMPLICIT_TLS_PORT = 465


class EmailSender(Protocol):
    async def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
    ) -> None: ...


class SMTPEmailSender:
    """Sends one message per SMTP connection. Port 465 uses TLS from the start, others STARTTLS."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "SMTPEmailSender":
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value(),
            from_email=settings.smtp_from_email,
            from_name=settings.smtp_from_name,
            timeout_seconds=settings.smtp_timeout_seconds,
        )

    def build_message(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self._from_name, self._from_email))
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        if html is not None:
            message.add_alternative(html, subtype="html")
        return message

    async def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
    ) -> None:
        import aiosmtplib

        implicit_tls = self._port == IMPLICIT_TLS_PORT
        try:
            await aiosmtplib.send(
                self.build_message(to, subject, text, html),
                hostname=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                use_tls=implicit_tls,
                start_tls=not implicit_tls,
                timeout=self._timeout_seconds,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise EmailSendError(str(exc)) from exc

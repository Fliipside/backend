from typing import Any

import aiosmtplib
import pytest
from pytest import MonkeyPatch

from app.clients.email import SMTPEmailSender
from app.core.config import Settings
from app.core.errors import EmailSendError


def make_sender(port: int = 587) -> SMTPEmailSender:
    return SMTPEmailSender.from_settings(
        Settings(
            smtp_host="smtp.example.com",
            smtp_port=port,
            smtp_username="sender@example.com",
            smtp_password="app-password",
            smtp_from_email="sender@example.com",
            smtp_from_name="Flipside",
            smtp_timeout_seconds=5,
        )
    )


def capture_send(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_send(message: Any, **kwargs: Any) -> None:
        calls.append({"message": message, **kwargs})

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    return calls


def test_build_message_sets_headers_and_both_bodies() -> None:
    message = make_sender().build_message(
        "user@example.com", "인증번호 안내", "인증번호: 123456", "<b>123456</b>"
    )

    assert message["From"] == "Flipside <sender@example.com>"
    assert message["To"] == "user@example.com"
    assert message["Subject"] == "인증번호 안내"
    assert message.get_body(("plain",)).get_content().strip() == "인증번호: 123456"
    assert message.get_body(("html",)).get_content().strip() == "<b>123456</b>"


@pytest.mark.anyio
async def test_send_uses_starttls_on_port_587(monkeypatch: MonkeyPatch) -> None:
    calls = capture_send(monkeypatch)

    await make_sender(587).send("user@example.com", "제목", "본문")

    assert len(calls) == 1
    call = calls[0]
    assert call["hostname"] == "smtp.example.com"
    assert call["port"] == 587
    assert call["username"] == "sender@example.com"
    assert call["password"] == "app-password"
    assert call["start_tls"] is True
    assert call["use_tls"] is False
    assert call["timeout"] == 5


@pytest.mark.anyio
async def test_send_uses_implicit_tls_on_port_465(monkeypatch: MonkeyPatch) -> None:
    calls = capture_send(monkeypatch)

    await make_sender(465).send("user@example.com", "제목", "본문")

    assert calls[0]["use_tls"] is True
    assert calls[0]["start_tls"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [aiosmtplib.SMTPAuthenticationError(535, "bad credentials"), OSError("unreachable")],
)
async def test_send_wraps_failures(monkeypatch: MonkeyPatch, error: Exception) -> None:
    async def failing_send(message: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(aiosmtplib, "send", failing_send)

    with pytest.raises(EmailSendError):
        await make_sender().send("user@example.com", "제목", "본문")

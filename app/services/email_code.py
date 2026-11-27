import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.email import EmailSender
from app.core.config import Settings
from app.core.errors import (
    EmailCodeAttemptsExceededError,
    EmailDailyLimitError,
    EmailRecipientLimitError,
    EmailResendCooldownError,
    EmailSendError,
    InvalidEmailCodeError,
)
from app.core.security import get_jwt_secret_key
from app.repositories import email_log as email_log_repository


logger = logging.getLogger(__name__)

PURPOSE_SIGNUP = "signup_verification"
PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSE_FIND_ID = "find_id"

CODE_LENGTH = 6
DAILY_COUNTER_EXPIRE_SECONDS = 2 * 24 * 60 * 60

EMAIL_TITLES = {
    PURPOSE_SIGNUP: "이메일 인증번호",
    PURPOSE_PASSWORD_RESET: "비밀번호 재설정 인증번호",
}


@dataclass(frozen=True)
class EmailJob:
    """What the background task needs to send one logged email."""

    email_log_id: UUID
    to: str
    subject: str
    text: str
    html: str


def _code_key(purpose: str, email: str) -> str:
    return f"email:code:{purpose}:{email}"


def _attempts_key(purpose: str, email: str) -> str:
    return f"email:attempts:{purpose}:{email}"


def _cooldown_key(purpose: str, email: str) -> str:
    return f"email:cooldown:{purpose}:{email}"


def _verified_key(email: str) -> str:
    return f"email:verified:{PURPOSE_SIGNUP}:{email}"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _daily_total_key() -> str:
    return f"email:daily:{_today()}"


def _daily_recipient_key(email: str) -> str:
    return f"email:daily:{_today()}:{email}"


def _hash_code(purpose: str, email: str, code: str, settings: Settings) -> str:
    # 6자리 숫자는 해시만으로는 쉽게 역산되므로 서버 비밀키로 HMAC을 건다.
    return hmac.new(
        get_jwt_secret_key(settings).encode("utf-8"),
        f"{purpose}:{email}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def issue_code(
        redis: Redis,
        purpose: str,
        email: str,
        settings: Settings,
) -> str:
    """Apply the send limits, then store a new code. Returns the plain code to email.

    The limits run for every request, whether or not an email is sent afterwards,
    so the response does not reveal if the address belongs to a user.
    """
    await check_daily_total(redis, settings)

    cooldown_left = await _start_cooldown(redis, purpose, email, settings)
    if cooldown_left:
        raise EmailResendCooldownError(cooldown_left)

    if not await _count_recipient(redis, email, settings):
        raise EmailRecipientLimitError

    code = f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(
            _code_key(purpose, email),
            _hash_code(purpose, email, code, settings),
            ex=settings.email_code_expire_seconds,
        )
        pipe.delete(_attempts_key(purpose, email))
        await pipe.execute()
    return code


async def check_daily_total(redis: Redis, settings: Settings) -> None:
    total = await redis.get(_daily_total_key())
    if total is not None and int(total) >= settings.email_daily_send_limit:
        raise EmailDailyLimitError


async def _start_cooldown(
        redis: Redis,
        purpose: str,
        email: str,
        settings: Settings,
) -> int:
    """Start the resend cooldown. Returns 0 when it started, else seconds left."""
    cooldown_key = _cooldown_key(purpose, email)
    started = await redis.set(
        cooldown_key,
        "1",
        ex=settings.email_code_resend_cooldown_seconds,
        nx=True,
    )
    if started:
        return 0
    remaining = await redis.ttl(cooldown_key)
    return max(int(remaining), 1)


async def _count_recipient(redis: Redis, email: str, settings: Settings) -> bool:
    """Count one send to this address. False when today's limit is used up."""
    recipient_key = _daily_recipient_key(email)
    recipient_count = await redis.incr(recipient_key)
    if recipient_count == 1:
        await redis.expire(recipient_key, DAILY_COUNTER_EXPIRE_SECONDS)
    return recipient_count <= settings.email_recipient_daily_limit


async def reserve_send(
        redis: Redis,
        purpose: str,
        email: str,
        settings: Settings,
) -> bool:
    """Apply the per-address limits without raising. False means skip this send.

    For mails that are a notice rather than a code: a skipped address already got
    the same mail within the cooldown, or has used up today's limit.
    """
    if await _start_cooldown(redis, purpose, email, settings):
        return False
    return await _count_recipient(redis, email, settings)


async def discard_code(redis: Redis, purpose: str, email: str) -> None:
    await redis.delete(_code_key(purpose, email), _attempts_key(purpose, email))


async def confirm_code(
        redis: Redis,
        purpose: str,
        email: str,
        code: str,
        settings: Settings,
) -> None:
    """Check a submitted code. A correct code is consumed and cannot be used again."""
    stored_hash = await redis.get(_code_key(purpose, email))
    if stored_hash is None:
        raise InvalidEmailCodeError

    attempts_key = _attempts_key(purpose, email)
    attempts = await redis.incr(attempts_key)
    if attempts == 1:
        await redis.expire(attempts_key, settings.email_code_expire_seconds)
    if attempts > settings.email_code_max_attempts:
        await discard_code(redis, purpose, email)
        raise EmailCodeAttemptsExceededError

    if not hmac.compare_digest(
        stored_hash,
        _hash_code(purpose, email, code, settings),
    ):
        raise InvalidEmailCodeError

    await discard_code(redis, purpose, email)


async def mark_email_verified(redis: Redis, email: str, settings: Settings) -> None:
    await redis.set(_verified_key(email), "1", ex=settings.email_verified_expire_seconds)


async def is_email_verified(redis: Redis, email: str) -> bool:
    return bool(await redis.exists(_verified_key(email)))


async def clear_email_verified(redis: Redis, email: str) -> None:
    await redis.delete(_verified_key(email))


EmailContent = tuple[str, str, str]


def build_find_id_email(email: str) -> EmailContent:
    subject = "[Flipside] 아이디 안내"
    text = (
        "Flipside 아이디 찾기 요청에 따라 아이디를 알려 드립니다.\n\n"
        f"아이디: {email}\n\n"
        "본인이 요청하지 않았다면 이 메일을 무시해 주세요."
    )
    html = (
        "<p>Flipside 아이디 찾기 요청에 따라 아이디를 알려 드립니다.</p>"
        f'<p style="font-size:20px;font-weight:bold">{escape(email)}</p>'
        "<p>본인이 요청하지 않았다면 이 메일을 무시해 주세요.</p>"
    )
    return subject, text, html


def build_code_email(
        purpose: str,
        code: str,
        settings: Settings,
) -> EmailContent:
    title = EMAIL_TITLES[purpose]
    minutes = max(settings.email_code_expire_seconds // 60, 1)
    subject = f"[Flipside] {title} 안내"
    text = (
        f"Flipside {title}입니다.\n\n"
        f"인증번호: {code}\n\n"
        f"{minutes}분 안에 입력해 주세요.\n"
        "본인이 요청하지 않았다면 이 메일을 무시해 주세요."
    )
    html = (
        f"<p>Flipside {title}입니다.</p>"
        f'<p style="font-size:24px;font-weight:bold;letter-spacing:4px">{code}</p>'
        f"<p>{minutes}분 안에 입력해 주세요.<br>"
        "본인이 요청하지 않았다면 이 메일을 무시해 주세요.</p>"
    )
    return subject, text, html


async def create_email_job(
        session: AsyncSession,
        redis: Redis,
        purpose: str,
        email: str,
        content: EmailContent,
) -> EmailJob:
    """Record the email as pending and count it against the daily total."""
    email_log = await email_log_repository.create_email_log(
        session,
        recipient=email,
        purpose=purpose,
    )
    await session.commit()

    total_key = _daily_total_key()
    if await redis.incr(total_key) == 1:
        await redis.expire(total_key, DAILY_COUNTER_EXPIRE_SECONDS)

    subject, text, html = content
    return EmailJob(
        email_log_id=email_log.id,
        to=email,
        subject=subject,
        text=text,
        html=html,
    )


async def deliver(
        sessionmaker: async_sessionmaker[AsyncSession],
        sender: EmailSender,
        job: EmailJob,
) -> None:
    """Send after the response has gone out, then write the result to email_logs."""
    error: str | None = None
    try:
        await sender.send(job.to, job.subject, job.text, job.html)
    except EmailSendError as exc:
        error = str(exc) or type(exc).__name__
        logger.warning("Email %s failed: %s", job.email_log_id, error)

    async with sessionmaker() as session:
        if error is None:
            await email_log_repository.mark_sent(session, job.email_log_id)
        else:
            await email_log_repository.mark_failed(session, job.email_log_id, error)
        await session.commit()

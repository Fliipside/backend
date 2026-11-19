from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_log import (
    EMAIL_STATUS_FAILED,
    EMAIL_STATUS_SENT,
    EmailLog,
)


ERROR_MAX_LENGTH = 500


async def create_email_log(
        session: AsyncSession,
        *,
        recipient: str,
        purpose: str,
) -> EmailLog:
    email_log = EmailLog(recipient=recipient, purpose=purpose)
    session.add(email_log)
    await session.flush()
    return email_log


async def mark_sent(session: AsyncSession, email_log_id: UUID) -> None:
    email_log = await session.get(EmailLog, email_log_id)
    if email_log is None:
        return
    email_log.status = EMAIL_STATUS_SENT
    email_log.sent_at = datetime.now(timezone.utc)


async def mark_failed(session: AsyncSession, email_log_id: UUID, error: str) -> None:
    email_log = await session.get(EmailLog, email_log_id)
    if email_log is None:
        return
    email_log.status = EMAIL_STATUS_FAILED
    email_log.error = error[:ERROR_MAX_LENGTH]

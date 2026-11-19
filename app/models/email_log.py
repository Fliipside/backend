from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


EMAIL_STATUS_PENDING = "pending"
EMAIL_STATUS_SENT = "sent"
EMAIL_STATUS_FAILED = "failed"


class EmailLog(Base):
    """One row per email handed to the SMTP server. The code itself is never stored.

    "sent" means the SMTP server accepted the message, not that it reached the inbox.
    """

    __tablename__ = "email_logs"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EMAIL_STATUS_PENDING,
    )
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    create_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

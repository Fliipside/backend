from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Redis queue name. Only memory_ingest_jobs.id goes in; the consumer reads
# voice_job_id and interaction_id from that row.
MEMORY_INGEST_QUEUE = "flipside:memory-ingest"


class MemoryIngestStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    TERMINAL = frozenset({SUCCEEDED, FAILED})


class MemoryIngestJob(Base):
    """Turning one analyzed conversation into memory (extraction, search vectors).

    The voice worker creates the row; a separate worker takes it from the queue.
    """

    __tablename__ = "memory_ingest_jobs"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    # Unique: one voice analysis is ingested once. The transcript is read from this job.
    voice_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("voice_analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Where the ingest result belongs.
    interaction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("interactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MemoryIngestStatus.QUEUED,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    create_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    update_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

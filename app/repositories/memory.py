from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryIngestJob, MemoryIngestStatus


async def get_memory_ingest_job(
        session: AsyncSession,
        job_id: UUID,
) -> MemoryIngestJob | None:
    return await session.get(MemoryIngestJob, job_id)


async def get_memory_ingest_job_by_voice_job(
        session: AsyncSession,
        voice_job_id: UUID,
) -> MemoryIngestJob | None:
    result = await session.execute(
        select(MemoryIngestJob).where(MemoryIngestJob.voice_job_id == voice_job_id)
    )
    return result.scalar_one_or_none()


async def create_memory_ingest_job(
        session: AsyncSession,
        *,
        voice_job_id: UUID,
        interaction_id: UUID,
) -> MemoryIngestJob | None:
    """Add a queued row. Returns None when this voice job already has one."""
    if await get_memory_ingest_job_by_voice_job(session, voice_job_id) is not None:
        return None
    job = MemoryIngestJob(
        voice_job_id=voice_job_id,
        interaction_id=interaction_id,
        status=MemoryIngestStatus.QUEUED,
        attempts=0,
    )
    session.add(job)
    await session.flush()
    return job


async def list_queued_job_ids(session: AsyncSession) -> list[UUID]:
    result = await session.execute(
        select(MemoryIngestJob.id)
        .where(MemoryIngestJob.status == MemoryIngestStatus.QUEUED)
        .order_by(MemoryIngestJob.create_at)
    )
    return list(result.scalars())

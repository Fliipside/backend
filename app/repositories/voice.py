from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice import VoiceAnalysisJob, VoiceAnalysisStatus, Voiceprint


async def get_voiceprint(session: AsyncSession, user_id: UUID) -> Voiceprint | None:
    return await session.get(Voiceprint, user_id)


async def save_voiceprint(
        session: AsyncSession,
        *,
        user_id: UUID,
        engine: str,
        vector: list[float],
) -> Voiceprint:
    voiceprint = await get_voiceprint(session, user_id)
    if voiceprint is None:
        voiceprint = Voiceprint(user_id=user_id, engine=engine, vector=vector)
        session.add(voiceprint)
    else:
        voiceprint.engine = engine
        voiceprint.vector = vector
    await session.flush()
    return voiceprint


async def create_voice_analysis_job(
        session: AsyncSession,
        *,
        job_id: UUID,
        user_id: UUID,
        object_key: str,
        original_filename: str,
        content_type: str | None,
        file_size: int,
) -> VoiceAnalysisJob:
    job = VoiceAnalysisJob(
        id=job_id,
        user_id=user_id,
        status=VoiceAnalysisStatus.QUEUED,
        object_key=object_key,
        original_filename=original_filename,
        content_type=content_type,
        file_size=file_size,
        attempts=0,
    )
    session.add(job)
    await session.flush()
    return job


async def get_voice_analysis_job(
        session: AsyncSession,
        job_id: UUID,
) -> VoiceAnalysisJob | None:
    return await session.get(VoiceAnalysisJob, job_id)


async def get_user_voice_analysis_job(
        session: AsyncSession,
        *,
        job_id: UUID,
        user_id: UUID,
) -> VoiceAnalysisJob | None:
    result = await session.execute(
        select(VoiceAnalysisJob).where(
            VoiceAnalysisJob.id == job_id,
            VoiceAnalysisJob.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_unfinished_job_ids(session: AsyncSession) -> list[UUID]:
    result = await session.execute(
        select(VoiceAnalysisJob.id)
        .where(VoiceAnalysisJob.status.not_in(VoiceAnalysisStatus.TERMINAL))
        .order_by(VoiceAnalysisJob.create_at)
    )
    return list(result.scalars())

import asyncio
import logging
import re
from pathlib import PurePath
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai import AIServiceClient
from app.clients.job_queue import RedisJobQueue
from app.clients.storage import ObjectStorage
from app.core.config import Settings
from app.core.errors import (
    AIServiceBadResponseError,
    AIServiceUpstreamError,
    EmptyFileError,
    FeatureNotReadyError,
    InvalidAudioError,
    ObjectStorageError,
    PayloadTooLargeError,
    QueueUnavailableError,
    StorageUnavailableError,
    VoiceAnalysisNotFoundError,
)
from app.models.user import User
from app.models.voice import VOICEPRINT_DIMENSIONS, VoiceAnalysisJob, VoiceAnalysisStatus
from app.repositories import voice as voice_repository
from app.schemas.voice import (
    AIVoiceprint,
    VoiceAnalysisCreateResponse,
    VoiceAnalysisResponse,
    VoiceEnrollResponse,
)


logger = logging.getLogger(__name__)

VOICE_ANALYSIS_QUEUE = "flipside:voice-analysis"
AI_ENROLL_PATH = "voice/enroll"
AI_ANALYZE_PATH = "voice/analyze"
RECORDING_KEY_PREFIX = "voice-recordings"
DEFAULT_FILENAME = "recording"
_EXTENSION_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")


def unwrap_ai_data(payload: dict[str, object]) -> object:
    """Return data from the ai ApiResponse(success, code, message, data)."""
    if payload.get("success") is not True or "data" not in payload:
        raise AIServiceBadResponseError
    return payload["data"]


async def measure_upload(file: UploadFile, max_bytes: int) -> int:
    def measure(content: BinaryIO) -> int:
        content.seek(0, 2)
        size = content.tell()
        content.seek(0)
        return size

    size = await asyncio.to_thread(measure, file.file)
    if size == 0:
        raise EmptyFileError
    if size > max_bytes:
        raise PayloadTooLargeError(max_bytes)
    return size


async def enroll_voice(
        file: UploadFile,
        user: User,
        session: AsyncSession,
        ai_client: AIServiceClient,
        settings: Settings,
) -> VoiceEnrollResponse:
    await measure_upload(file, settings.voice_enroll_max_bytes)
    try:
        payload = await ai_client.post_multipart(
            AI_ENROLL_PATH,
            files={"file": (_filename(file), file.file, file.content_type)},
            timeout=settings.ai_enroll_timeout_seconds,
        )
    except AIServiceUpstreamError as exc:
        if exc.status_code == 400 and exc.code == "INVALID_AUDIO":
            raise InvalidAudioError from exc
        if exc.status_code == 501:
            raise FeatureNotReadyError("voice enroll") from exc
        raise

    try:
        voiceprint = AIVoiceprint.model_validate(unwrap_ai_data(payload))
    except ValidationError as exc:
        raise AIServiceBadResponseError from exc

    saved = await voice_repository.save_voiceprint(
        session,
        user_id=user.id,
        engine=voiceprint.engine,
        vector=voiceprint.vector,
    )
    await session.commit()
    await session.refresh(saved)
    return VoiceEnrollResponse(
        engine=saved.engine,
        dimensions=VOICEPRINT_DIMENSIONS,
        update_at=saved.update_at,
    )


async def create_voice_analysis(
        file: UploadFile,
        user: User,
        session: AsyncSession,
        storage: ObjectStorage,
        queue: RedisJobQueue,
        settings: Settings,
) -> VoiceAnalysisCreateResponse:
    size = await measure_upload(file, settings.voice_recording_max_bytes)
    filename = _filename(file)
    job_id = uuid4()
    object_key = build_recording_key(user.id, job_id, filename)

    try:
        await storage.upload(object_key, file.file, file.content_type)
    except ObjectStorageError as exc:
        logger.exception("Failed to upload recording to object storage")
        raise StorageUnavailableError from exc

    job = await voice_repository.create_voice_analysis_job(
        session,
        job_id=job_id,
        user_id=user.id,
        object_key=object_key,
        original_filename=filename[:255],
        content_type=(file.content_type or None) and file.content_type[:100],
        file_size=size,
    )
    await session.commit()

    try:
        await queue.enqueue(str(job.id))
    except (RedisError, OSError) as exc:
        logger.exception("Failed to enqueue voice analysis job %s", job.id)
        job.status = VoiceAnalysisStatus.FAILED
        job.error_code = "QUEUE_UNAVAILABLE"
        job.error_message = "작업 큐에 연결할 수 없습니다."
        await session.commit()
        raise QueueUnavailableError from exc

    await session.refresh(job)
    return VoiceAnalysisCreateResponse(
        job_id=job.id,
        status=job.status,
        create_at=job.create_at,
    )


async def get_voice_analysis(
        job_id: UUID,
        user: User,
        session: AsyncSession,
) -> VoiceAnalysisResponse:
    job = await voice_repository.get_user_voice_analysis_job(
        session,
        job_id=job_id,
        user_id=user.id,
    )
    if job is None:
        raise VoiceAnalysisNotFoundError
    return to_voice_analysis_response(job)


def to_voice_analysis_response(job: VoiceAnalysisJob) -> VoiceAnalysisResponse:
    return VoiceAnalysisResponse(
        job_id=job.id,
        status=job.status,
        original_filename=job.original_filename,
        used_voiceprint=job.used_voiceprint_engine is not None,
        error_code=job.error_code,
        error_message=job.error_message,
        result=job.result if job.status == VoiceAnalysisStatus.SUCCEEDED else None,
        create_at=job.create_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def build_recording_key(user_id: UUID, job_id: UUID, filename: str) -> str:
    extension = PurePath(filename).suffix.lower()
    if not _EXTENSION_PATTERN.match(extension):
        extension = ""
    return f"{RECORDING_KEY_PREFIX}/{user_id}/{job_id}{extension}"


def _filename(file: UploadFile) -> str:
    return PurePath(file.filename or "").name or DEFAULT_FILENAME

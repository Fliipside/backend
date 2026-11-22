import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
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
    CustomerNotFoundError,
    FeatureNotReadyError,
    InvalidAudioError,
    InvalidRequestError,
    ObjectStorageError,
    QueueUnavailableError,
    StorageUnavailableError,
    VoiceAnalysisNotFoundError,
)
from app.models.interaction import (
    INTERACTION_TITLE_MAX_LENGTH,
    Interaction,
    InteractionKind,
)
from app.models.user import User
from app.models.voice import VOICEPRINT_DIMENSIONS, VoiceAnalysisJob, VoiceAnalysisStatus
from app.repositories import customer as customer_repository
from app.repositories import interaction as interaction_repository
from app.repositories import voice as voice_repository
from app.schemas.voice import (
    AIVoiceprint,
    VoiceAnalysisCreateResponse,
    VoiceAnalysisResponse,
    VoiceEnrollResponse,
)
from app.services.upload import measure_upload


logger = logging.getLogger(__name__)

VOICE_ANALYSIS_QUEUE = "flipside:voice-analysis"
AI_ENROLL_PATH = "voice/enroll"
AI_ANALYZE_PATH = "voice/analyze"
RECORDING_KEY_PREFIX = "voice-recordings"
DEFAULT_FILENAME = "recording"
_EXTENSION_PATTERN = re.compile(r"^\.[a-z0-9]{1,10}$")
_CUSTOMER_ID_PATTERN = re.compile(r"^[0-9]{1,10}$")
_MAX_CUSTOMER_ID = 2**31 - 1  # customers.id is a 32-bit integer


@dataclass(frozen=True)
class InteractionInput:
    customer_id: int
    kind: str
    title: str
    occurred_at: datetime


def unwrap_ai_data(payload: dict[str, object]) -> object:
    """Return data from the ai ApiResponse(success, code, message, data)."""
    if payload.get("success") is not True or "data" not in payload:
        raise AIServiceBadResponseError
    return payload["data"]


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
        *,
        customer_id: str | None,
        kind: str | None = None,
        title: str | None = None,
        occurred_at: str | None = None,
) -> VoiceAnalysisCreateResponse:
    # Everything is checked before the recording goes to object storage.
    filename = _filename(file)
    interaction_input = parse_interaction_input(
        customer_id=customer_id,
        kind=kind,
        title=title,
        occurred_at=occurred_at,
        filename=filename,
    )
    size = await measure_upload(file, settings.voice_recording_max_bytes)
    # A customer owned by someone else is reported the same way as a missing one.
    customer = await customer_repository.get_user_customer(
        session,
        customer_id=interaction_input.customer_id,
        owner_user_id=user.id,
    )
    if customer is None:
        raise CustomerNotFoundError

    job_id = uuid4()
    object_key = build_recording_key(user.id, job_id, filename)

    try:
        await storage.upload(object_key, file.file, file.content_type)
    except ObjectStorageError as exc:
        logger.exception("Failed to upload recording to object storage")
        raise StorageUnavailableError from exc

    # The interaction and the job are committed together.
    interaction = await interaction_repository.create_interaction(
        session,
        customer_id=customer.id,
        owner_user_id=user.id,
        kind=interaction_input.kind,
        title=interaction_input.title,
        occurred_at=interaction_input.occurred_at,
    )
    job = await voice_repository.create_voice_analysis_job(
        session,
        job_id=job_id,
        user_id=user.id,
        interaction_id=interaction.id,
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
        interaction_id=interaction.id,
        status=job.status,
        create_at=job.create_at,
    )


async def get_voice_analysis(
        job_id: UUID,
        user: User,
        session: AsyncSession,
) -> VoiceAnalysisResponse:
    found = await voice_repository.get_user_voice_analysis_job(
        session,
        job_id=job_id,
        user_id=user.id,
    )
    if found is None:
        raise VoiceAnalysisNotFoundError
    job, interaction = found
    return to_voice_analysis_response(job, interaction)


def to_voice_analysis_response(
        job: VoiceAnalysisJob,
        interaction: Interaction | None,
) -> VoiceAnalysisResponse:
    return VoiceAnalysisResponse(
        job_id=job.id,
        interaction_id=interaction.id if interaction else None,
        customer_id=interaction.customer_id if interaction else None,
        kind=interaction.kind if interaction else None,
        title=interaction.title if interaction else None,
        occurred_at=interaction.occurred_at if interaction else None,
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


def parse_interaction_input(
        *,
        customer_id: str | None,
        kind: str | None,
        title: str | None,
        occurred_at: str | None,
        filename: str,
) -> InteractionInput:
    """Check the form values of an upload. Blank optional values use the default."""
    customer_id = (customer_id or "").strip()
    if not customer_id:
        raise InvalidRequestError("customer_id는 필수입니다.")
    if (
        not _CUSTOMER_ID_PATTERN.match(customer_id)
        or not 1 <= int(customer_id) <= _MAX_CUSTOMER_ID
    ):
        raise InvalidRequestError("customer_id는 정수여야 합니다.")

    kind = (kind or "").strip() or InteractionKind.MEETING
    if kind not in InteractionKind.ALL:
        raise InvalidRequestError("kind는 meeting 또는 call이어야 합니다.")

    title = (title or "").strip()
    if len(title) > INTERACTION_TITLE_MAX_LENGTH:
        raise InvalidRequestError(
            f"title은 {INTERACTION_TITLE_MAX_LENGTH}자를 넘을 수 없습니다."
        )
    if not title:
        title = _default_title(filename)

    occurred_at = (occurred_at or "").strip()
    if not occurred_at:
        occurred = datetime.now(timezone.utc)
    else:
        try:
            occurred = datetime.fromisoformat(occurred_at)
        except ValueError as exc:
            raise InvalidRequestError(
                "occurred_at은 ISO 8601 형식이어야 합니다. 예: 2026-11-20T14:00:00+09:00"
            ) from exc
        if occurred.utcoffset() is None:
            raise InvalidRequestError(
                "occurred_at에는 시간대가 있어야 합니다. 예: 2026-11-20T14:00:00+09:00"
            )
        occurred = occurred.astimezone(timezone.utc)

    return InteractionInput(
        customer_id=int(customer_id),
        kind=kind,
        title=title,
        occurred_at=occurred,
    )


def _default_title(filename: str) -> str:
    """The upload file name without its extension."""
    title = PurePath(filename).stem.strip() or DEFAULT_FILENAME
    return title[:INTERACTION_TITLE_MAX_LENGTH]


def build_recording_key(user_id: UUID, job_id: UUID, filename: str) -> str:
    extension = PurePath(filename).suffix.lower()
    if not _EXTENSION_PATTERN.match(extension):
        extension = ""
    return f"{RECORDING_KEY_PREFIX}/{user_id}/{job_id}{extension}"


def _filename(file: UploadFile) -> str:
    return PurePath(file.filename or "").name or DEFAULT_FILENAME

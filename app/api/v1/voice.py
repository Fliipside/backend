from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_ai_client,
    get_current_user,
    get_object_storage,
    get_settings_from_app,
    get_voice_analysis_queue,
)
from app.clients.ai import AIServiceClient
from app.clients.job_queue import RedisJobQueue
from app.clients.storage import ObjectStorage
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.response import ApiResponse
from app.schemas.voice import (
    VoiceAnalysisCreateResponse,
    VoiceAnalysisResponse,
    VoiceEnrollResponse,
)
from app.services.voice import (
    create_voice_analysis,
    enroll_voice,
    get_voice_analysis,
)

router = APIRouter()


@router.post("/enroll", response_model=ApiResponse[VoiceEnrollResponse])
async def enroll(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ai_client: Annotated[AIServiceClient, Depends(get_ai_client)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[VoiceEnrollResponse]:
    result = await enroll_voice(file, user, session, ai_client, settings)
    return ApiResponse[VoiceEnrollResponse].ok(data=result)


@router.post(
    "/analyses",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiResponse[VoiceAnalysisCreateResponse],
)
async def create_analysis(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    queue: Annotated[RedisJobQueue, Depends(get_voice_analysis_queue)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    # Read as plain text and checked in the service, so a bad value is a 400
    # with a message that names the field.
    customer_id: Annotated[str | None, Form()] = None,
    kind: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    occurred_at: Annotated[str | None, Form()] = None,
) -> ApiResponse[VoiceAnalysisCreateResponse]:
    result = await create_voice_analysis(
        file,
        user,
        session,
        storage,
        queue,
        settings,
        customer_id=customer_id,
        kind=kind,
        title=title,
        occurred_at=occurred_at,
    )
    return ApiResponse[VoiceAnalysisCreateResponse].ok(
        data=result,
        code="ACCEPTED",
        message="음성 분석 작업이 등록되었습니다.",
    )


@router.get(
    "/analyses/{job_id}",
    response_model=ApiResponse[VoiceAnalysisResponse],
)
async def get_analysis(
    job_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[VoiceAnalysisResponse]:
    result = await get_voice_analysis(job_id, user, session)
    return ApiResponse[VoiceAnalysisResponse].ok(data=result)

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_object_storage, get_settings_from_app
from app.clients.storage import ObjectStorage
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.image import ImageResponse
from app.schemas.response import ApiResponse
from app.services.image import create_image, delete_image, get_image

router = APIRouter()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[ImageResponse],
)
async def upload(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[ImageResponse]:
    result = await create_image(file, user, session, storage, settings)
    return ApiResponse[ImageResponse].ok(
        data=result,
        code="CREATED",
        message="이미지가 저장되었습니다.",
    )


@router.get("/{image_id}", response_model=ApiResponse[ImageResponse])
async def get(
    image_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[ImageResponse]:
    result = await get_image(image_id, user, session, storage, settings)
    return ApiResponse[ImageResponse].ok(data=result)


@router.delete("/{image_id}", response_model=ApiResponse[None])
async def delete(
    image_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> ApiResponse[None]:
    await delete_image(image_id, user, session, storage)
    return ApiResponse[None].ok(message="이미지가 삭제되었습니다.")

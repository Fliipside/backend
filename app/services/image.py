import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.storage import ObjectStorage
from app.core.config import Settings
from app.core.errors import (
    ImageNotFoundError,
    InvalidImageError,
    ObjectStorageError,
    StorageUnavailableError,
)
from app.models.image import Image
from app.models.user import User
from app.repositories import image as image_repository
from app.schemas.image import ImageResponse
from app.services.upload import measure_upload


logger = logging.getLogger(__name__)

IMAGE_KEY_PREFIX = "images"
_HEADER_BYTES = 12
_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def detect_image_type(header: bytes) -> str | None:
    """Identify the format from the file's first bytes; the client's Content-Type is not trusted."""
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


async def create_image(
        file: UploadFile,
        user: User,
        session: AsyncSession,
        storage: ObjectStorage,
        settings: Settings,
) -> ImageResponse:
    size = await measure_upload(file, settings.image_max_bytes)
    content_type = detect_image_type(await file.read(_HEADER_BYTES))
    if content_type is None:
        raise InvalidImageError
    await file.seek(0)

    image_id = uuid4()
    object_key = f"{IMAGE_KEY_PREFIX}/{user.id}/{image_id}{_EXTENSIONS[content_type]}"

    try:
        await storage.upload(object_key, file.file, content_type)
    except ObjectStorageError as exc:
        logger.exception("Failed to upload image to object storage")
        raise StorageUnavailableError from exc

    try:
        image = await image_repository.create_image(
            session,
            image_id=image_id,
            user_id=user.id,
            object_key=object_key,
            content_type=content_type,
            file_size=size,
        )
        await session.commit()
        await session.refresh(image)
    except Exception:
        # No row points at the uploaded file, so nobody could ever delete it later.
        try:
            await storage.delete(object_key)
        except ObjectStorageError:
            logger.exception("Failed to remove orphan image %s", object_key)
        raise

    return _to_response(image, storage, settings)


async def get_image(
        image_id: UUID,
        user: User,
        session: AsyncSession,
        storage: ObjectStorage,
        settings: Settings,
) -> ImageResponse:
    image = await _get_user_image(image_id, user, session)
    return _to_response(image, storage, settings)


async def delete_image(
        image_id: UUID,
        user: User,
        session: AsyncSession,
        storage: ObjectStorage,
) -> None:
    image = await _get_user_image(image_id, user, session)
    # File first: if this fails the row stays and the client can retry.
    try:
        await storage.delete(image.object_key)
    except ObjectStorageError as exc:
        logger.exception("Failed to delete image %s from object storage", image.id)
        raise StorageUnavailableError from exc
    await image_repository.delete_image(session, image)
    await session.commit()


async def _get_user_image(image_id: UUID, user: User, session: AsyncSession) -> Image:
    image = await image_repository.get_user_image(
        session,
        image_id=image_id,
        user_id=user.id,
    )
    if image is None:
        raise ImageNotFoundError
    return image


def _to_response(image: Image, storage: ObjectStorage, settings: Settings) -> ImageResponse:
    expires_in = settings.image_url_expire_seconds
    try:
        url = storage.presigned_get_url(image.object_key, expires_in)
    except ObjectStorageError as exc:
        logger.exception("Failed to sign image URL for %s", image.id)
        raise StorageUnavailableError from exc
    return ImageResponse(
        image_id=image.id,
        url=url,
        url_expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        content_type=image.content_type,
        file_size=image.file_size,
        create_at=image.create_at,
    )

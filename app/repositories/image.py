from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image import Image


async def create_image(
        session: AsyncSession,
        *,
        image_id: UUID,
        user_id: UUID,
        object_key: str,
        content_type: str,
        file_size: int,
) -> Image:
    image = Image(
        id=image_id,
        user_id=user_id,
        object_key=object_key,
        content_type=content_type,
        file_size=file_size,
    )
    session.add(image)
    await session.flush()
    return image


async def get_user_image(
        session: AsyncSession,
        *,
        image_id: UUID,
        user_id: UUID,
) -> Image | None:
    result = await session.execute(
        select(Image).where(
            Image.id == image_id,
            Image.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_image(session: AsyncSession, image: Image) -> None:
    await session.delete(image)
    await session.flush()

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(
        session: AsyncSession,
        *,
        email: str,
        password_hash: str,
        nickname: str,
) -> User:
    user = User(
        email=email,
        password_hash=password_hash,
        nickname=nickname,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user

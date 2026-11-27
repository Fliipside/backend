from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def list_active_users_by_name_and_phone(
        session: AsyncSession,
        name: str,
        phone: str,
) -> list[User]:
    result = await session.execute(
        select(User)
        .where(
            User.name == name,
            User.phone == phone,
            User.is_active.is_(True),
        )
        .order_by(User.create_at)
    )
    return list(result.scalars())


async def update_password_hash(
        session: AsyncSession,
        user: User,
        password_hash: str,
) -> None:
    user.password_hash = password_hash
    await session.flush()


async def create_user(
        session: AsyncSession,
        *,
        email: str,
        password_hash: str,
        nickname: str,
        name: str,
        phone: str,
        company: str,
) -> User:
    user = User(
        email=email,
        password_hash=password_hash,
        nickname=nickname,
        name=name,
        phone=phone,
        company=company,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user

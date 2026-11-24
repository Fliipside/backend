from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interaction import Interaction


async def create_interaction(
        session: AsyncSession,
        *,
        customer_id: int,
        owner_user_id: UUID,
        kind: str,
        title: str,
        occurred_at: datetime,
) -> Interaction:
    interaction = Interaction(
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        kind=kind,
        title=title,
        occurred_at=occurred_at,
    )
    session.add(interaction)
    await session.flush()
    return interaction

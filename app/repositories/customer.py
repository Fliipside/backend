from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer


async def create_customer(
        session: AsyncSession,
        *,
        owner_user_id: UUID,
        company_name: str,
        industry: str | None,
        name: str,
        department: str | None,
        title: str | None,
) -> Customer:
    customer = Customer(
        owner_user_id=owner_user_id,
        company_name=company_name,
        industry=industry,
        name=name,
        department=department,
        title=title,
    )
    session.add(customer)
    await session.flush()
    # Load the values the database filled in (create_at, update_at).
    await session.refresh(customer)
    return customer


async def list_user_customers(
        session: AsyncSession,
        owner_user_id: UUID,
) -> list[Customer]:
    result = await session.execute(
        select(Customer)
        .where(Customer.owner_user_id == owner_user_id)
        # id breaks ties between customers created at the same moment.
        .order_by(Customer.create_at.desc(), Customer.id.desc())
    )
    return list(result.scalars())


async def get_user_customer(
        session: AsyncSession,
        *,
        customer_id: int,
        owner_user_id: UUID,
) -> Customer | None:
    result = await session.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.owner_user_id == owner_user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_customer(
        session: AsyncSession,
        customer: Customer,
        changes: dict[str, Any],
) -> Customer:
    for field, value in changes.items():
        setattr(customer, field, value)
    await session.flush()
    # update_at is set by the database, so read it back.
    await session.refresh(customer)
    return customer

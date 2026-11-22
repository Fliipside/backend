from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CustomerNotFoundError
from app.models.customer import Customer
from app.models.user import User
from app.repositories import customer as customer_repository
from app.schemas.customer import (
    CustomerCreateRequest,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdateRequest,
)


async def create_customer(
        payload: CustomerCreateRequest,
        user: User,
        session: AsyncSession,
) -> CustomerResponse:
    customer = await customer_repository.create_customer(
        session,
        owner_user_id=user.id,
        **payload.model_dump(),
    )
    response = _to_response(customer)
    await session.commit()
    return response


async def list_customers(user: User, session: AsyncSession) -> CustomerListResponse:
    customers = await customer_repository.list_user_customers(session, user.id)
    return CustomerListResponse(customers=[_to_response(c) for c in customers])


async def get_customer(
        customer_id: int,
        user: User,
        session: AsyncSession,
) -> CustomerResponse:
    return _to_response(await _get_user_customer(customer_id, user, session))


async def update_customer(
        customer_id: int,
        payload: CustomerUpdateRequest,
        user: User,
        session: AsyncSession,
) -> CustomerResponse:
    customer = await _get_user_customer(customer_id, user, session)
    customer = await customer_repository.update_customer(
        session,
        customer,
        payload.model_dump(exclude_unset=True),
    )
    response = _to_response(customer)
    await session.commit()
    return response


async def _get_user_customer(
        customer_id: int,
        user: User,
        session: AsyncSession,
) -> Customer:
    # A customer owned by someone else is reported the same way as a missing one.
    customer = await customer_repository.get_user_customer(
        session,
        customer_id=customer_id,
        owner_user_id=user.id,
    )
    if customer is None:
        raise CustomerNotFoundError
    return customer


def _to_response(customer: Customer) -> CustomerResponse:
    return CustomerResponse(
        customer_id=customer.id,
        company_name=customer.company_name,
        industry=customer.industry,
        name=customer.name,
        department=customer.department,
        title=customer.title,
        create_at=customer.create_at,
        update_at=customer.update_at,
    )

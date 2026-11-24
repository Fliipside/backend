from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.customer import (
    CustomerCreateRequest,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdateRequest,
)
from app.schemas.response import ApiResponse
from app.services.customer import (
    create_customer,
    get_customer,
    list_customers,
    update_customer,
)

router = APIRouter()

# The column is a 32-bit integer; a larger value would fail inside PostgreSQL.
CustomerId = Annotated[int, Path(ge=1, le=2**31 - 1)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[CustomerResponse],
)
async def create(
    payload: CustomerCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[CustomerResponse]:
    result = await create_customer(payload, user, session)
    return ApiResponse[CustomerResponse].ok(
        data=result,
        code="CREATED",
        message="고객이 등록되었습니다.",
    )


@router.get("", response_model=ApiResponse[CustomerListResponse])
async def list_all(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[CustomerListResponse]:
    result = await list_customers(user, session)
    return ApiResponse[CustomerListResponse].ok(data=result)


@router.get("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def get(
    customer_id: CustomerId,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[CustomerResponse]:
    result = await get_customer(customer_id, user, session)
    return ApiResponse[CustomerResponse].ok(data=result)


@router.patch("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def update(
    customer_id: CustomerId,
    payload: CustomerUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[CustomerResponse]:
    result = await update_customer(customer_id, payload, user, session)
    return ApiResponse[CustomerResponse].ok(
        data=result,
        message="고객 정보가 수정되었습니다.",
    )

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, StringConstraints, model_validator


def _blank_to_none(value: object) -> object:
    # 선택 항목은 빈 문자열과 공백만 있는 값을 "없음"으로 저장한다.
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _text(max_length: int, min_length: int = 0) -> StringConstraints:
    return StringConstraints(
        strip_whitespace=True,
        min_length=min_length,
        max_length=max_length,
    )


CompanyName = Annotated[str, _text(100, min_length=1)]
PersonName = Annotated[str, _text(50, min_length=1)]
Industry = Annotated[Annotated[str, _text(100)] | None, BeforeValidator(_blank_to_none)]
Department = Annotated[Annotated[str, _text(100)] | None, BeforeValidator(_blank_to_none)]
Title = Annotated[Annotated[str, _text(50)] | None, BeforeValidator(_blank_to_none)]

_REQUIRED_FIELDS = ("company_name", "name")


class CustomerCreateRequest(BaseModel):
    company_name: CompanyName
    industry: Industry = None
    name: PersonName
    department: Department = None
    title: Title = None


class CustomerUpdateRequest(BaseModel):
    """Only the fields present in the body are changed."""

    company_name: CompanyName | None = None
    industry: Industry = None
    name: PersonName | None = None
    department: Department = None
    title: Title = None

    @model_validator(mode="after")
    def reject_null_for_required_fields(self) -> Self:
        # 선택 항목은 null로 비울 수 있지만 필수 항목은 비울 수 없다.
        for field in _REQUIRED_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


class CustomerResponse(BaseModel):
    customer_id: int
    company_name: str
    industry: str | None
    name: str
    department: str | None
    title: str | None
    create_at: datetime
    update_at: datetime


class CustomerListResponse(BaseModel):
    customers: list[CustomerResponse]

from typing import Generic, Self, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    code: str
    message: str
    data: T | None

    @classmethod
    def ok(
        cls,
        data: T | None = None,
        *,
        code: str = "SUCCESS",
        message: str = "요청이 성공적으로 처리되었습니다.",
    ) -> Self:
        return cls(
            success=True,
            code=code,
            message=message,
            data=data,
        )

    @classmethod
    def fail(
        cls,
        *,
        code: str = "INVALID_REQUEST",
        message: str = "잘못된 요청입니다.",
    ) -> Self:
        return cls(
            success=False,
            code=code,
            message=message,
            data=None,
        )
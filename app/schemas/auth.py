import re
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)


def require_letter_and_digit(password: str) -> str:
    # 프론트 가입 화면과 같은 규칙: 영문과 숫자를 모두 포함해야 한다.
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("password must contain a letter and a digit")
    return password


# 가입할 때와 재설정할 때 같은 규칙을 쓴다.
Password = Annotated[
    str,
    Field(min_length=8, max_length=128),
    AfterValidator(require_letter_and_digit),
]


class SignupRequest(BaseModel):
    email: EmailStr
    password: Password
    nickname: str = Field(min_length=1, max_length=50)
    # 아이디 찾기에서 이름과 함께 비교할 값이라 앞뒤 공백을 떼고 저장한다.
    company: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ]


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: Password


class EmailCodeSentResponse(BaseModel):
    expires_in: int
    resend_after: int


class EmailVerifiedResponse(BaseModel):
    email: str
    expires_in: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    nickname: str
    company: str

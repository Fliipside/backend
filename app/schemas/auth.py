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


def normalize_phone(phone: str) -> str:
    # 010-1234-5678, 010 1234 5678, 01012345678을 모두 받아 숫자만 남긴다.
    digits = re.sub(r"[\s-]", "", phone)
    if not re.fullmatch(r"01\d{8,9}", digits):
        raise ValueError("phone must be a mobile number like 010-1234-5678")
    return digits


# 아이디 찾기에서 그대로 비교하므로 가입과 찾기에 같은 규칙을 쓴다.
PersonName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
Phone = Annotated[str, Field(max_length=20), AfterValidator(normalize_phone)]


class SignupRequest(BaseModel):
    email: EmailStr
    password: Password
    nickname: str = Field(min_length=1, max_length=50)
    name: PersonName
    phone: Phone
    # 앞뒤 공백을 떼고 저장한다.
    company: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ]


class FindIdRequest(BaseModel):
    name: PersonName
    phone: Phone


class FindIdResponse(BaseModel):
    # 일치하는 계정마다 가린 이메일 하나. 예: as********@gmail.com
    emails: list[str]


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
    name: str
    phone: str
    company: str

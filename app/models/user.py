from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    nickname: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # 이 항목이 생기기 전에 가입한 사용자는 빈 문자열로 남는다.
    company: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
        server_default="",
    )

    # 아이디 찾기에 쓰는 본인 확인 값. 이 항목이 생기기 전에 가입한 사용자는
    # 빈 문자열로 남아 아이디 찾기에 걸리지 않는다.
    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
        server_default="",
    )

    # 숫자만 저장한다. 예: 01012345678. 인증 없이 받는 값이라 중복을 허용한다.
    phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="",
        server_default="",
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

    create_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    update_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
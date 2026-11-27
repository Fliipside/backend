from typing import Annotated

from pydantic import BaseModel, StringConstraints


# 방 이름은 URL과 로그에 그대로 쓰이므로 안전한 문자만 받는다.
RoomName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class LiveKitTokenRequest(BaseModel):
    room_name: RoomName


class LiveKitTokenResponse(BaseModel):
    url: str
    token: str
    room_name: str
    identity: str
    expires_in: int

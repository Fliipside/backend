from pydantic import BaseModel

from app.schemas.response import ApiResponse


class SampleData(BaseModel):
    id: int
    name: str


def test_ok_response_with_object() -> None:
    data = SampleData(id=1, name="flipside")

    response = ApiResponse[SampleData].ok(data)

    assert response.model_dump() == {
        "success": True,
        "code": "SUCCESS",
        "message": "요청이 성공적으로 처리되었습니다.",
        "data": {
            "id": 1,
            "name": "flipside",
        },
    }


def test_ok_response_with_list() -> None:
    response = ApiResponse[list[int]].ok([1, 2, 3])

    assert response.success is True
    assert response.data == [1, 2, 3]


def test_fail_response() -> None:
    response = ApiResponse[None].fail(
        code="INVALID_REQUEST",
        message="잘못된 요청입니다.",
    )

    assert response.model_dump() == {
        "success": False,
        "code": "INVALID_REQUEST",
        "message": "잘못된 요청입니다.",
        "data": None,
    }
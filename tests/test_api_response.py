from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        yield test_client


def test_health_response(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "SUCCESS",
        "message": "요청이 성공적으로 처리되었습니다.",
        "data": {
            "status": "ok",
        },
    }


def test_feature_not_ready_response(client: TestClient) -> None:
    response = client.post(
        "/api/v1/relationship/infer",
        json={"messages": [{"speaker": "A", "text": "hello"}]},
    )

    assert response.status_code == 501
    assert response.json() == {
        "success": False,
        "code": "FEATURE_NOT_READY",
        "message": "relationship API workflow is not implemented yet",
        "data": None,
    }


def test_ai_service_not_configured_response(client: TestClient) -> None:
    response = client.post(
        "/api/v1/emotion/infer",
        json={"text": "hello"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "code": "SERVICE_UNAVAILABLE",
        "message": "AI service is not configured",
        "data": None,
    }


def test_validation_error_response(client: TestClient) -> None:
    response = client.post(
        "/api/v1/relationship/infer",
        json={},
    )

    assert response.status_code == 422
    assert response.json() == {
        "success": False,
        "code": "INVALID_REQUEST",
        "message": "요청 값이 올바르지 않습니다.",
        "data": None,
    }


def test_not_found_response(client: TestClient) -> None:
    response = client.get("/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "code": "NOT_FOUND",
        "message": "Not Found",
        "data": None,
    }
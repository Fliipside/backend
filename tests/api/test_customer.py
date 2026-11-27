import asyncio
from collections.abc import Iterator
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.models.customer import Customer
from tests.conftest import mark_email_verified


CUSTOMER = {
    "company_name": "노바테크",
    "industry": "IT·솔루션",
    "name": "김민준",
    "department": "사업개발팀",
    "title": "부장",
}


@pytest.fixture
def sessionmaker(tmp_path: Path) -> async_sessionmaker:
    path = tmp_path / "customer.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return async_sessionmaker(
        create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool),
        expire_on_commit=False,
    )


@pytest.fixture
def client(sessionmaker: async_sessionmaker) -> Iterator[TestClient]:
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
        jwt_secret_key="test-secret-key-with-enough-length-1234",
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        app.state.db_sessionmaker = sessionmaker
        app.state.redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        yield test_client


def auth_header(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    mark_email_verified(client, email)
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "password1234",
            "nickname": "tester",
            "name": "홍길동",
            "phone": "010-1234-5678",
            "company": "Flipside",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def create(client: TestClient, headers: dict[str, str], **overrides):
    return client.post(
        "/api/v1/customers",
        headers=headers,
        json={**CUSTOMER, **overrides},
    )


def stored_customers(sessionmaker: async_sessionmaker) -> list[Customer]:
    async def fetch() -> list[Customer]:
        async with sessionmaker() as session:
            return list((await session.execute(select(Customer))).scalars())

    return asyncio.run(fetch())


def test_create_stores_customer_for_current_user(
    client: TestClient,
    sessionmaker: async_sessionmaker,
) -> None:
    headers = auth_header(client)

    response = create(client, headers)

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "CREATED"
    data = body["data"]
    assert isinstance(data["customer_id"], int)
    assert {key: data[key] for key in CUSTOMER} == CUSTOMER
    assert data["create_at"] and data["update_at"]
    assert "owner_user_id" not in data

    [customer] = stored_customers(sessionmaker)
    assert customer.id == data["customer_id"]
    me = client.get("/api/v1/auth/me", headers=headers).json()["data"]
    assert str(customer.owner_user_id) == me["id"]


def test_create_accepts_only_required_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/customers",
        headers=auth_header(client),
        json={"company_name": "노바테크", "name": "김민준"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["industry"] is None
    assert data["department"] is None
    assert data["title"] is None


def test_create_strips_whitespace_and_stores_blank_optional_as_null(
    client: TestClient,
) -> None:
    response = create(
        client,
        auth_header(client),
        company_name="  노바테크 ",
        name=" 김민준 ",
        industry="   ",
        department="",
        title=" 부장 ",
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["company_name"] == "노바테크"
    assert data["name"] == "김민준"
    assert data["industry"] is None
    assert data["department"] is None
    assert data["title"] == "부장"


@pytest.mark.parametrize(
    "overrides",
    [
        {"company_name": None},
        {"company_name": "   "},
        {"name": ""},
        {"company_name": "가" * 101},
        {"name": "가" * 51},
        {"industry": "가" * 101},
        {"department": "가" * 101},
        {"title": "가" * 51},
    ],
)
def test_create_rejects_invalid_values(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    overrides: dict,
) -> None:
    response = create(client, auth_header(client), **overrides)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    assert stored_customers(sessionmaker) == []


def test_create_rejects_missing_required_field(client: TestClient) -> None:
    response = client.post(
        "/api/v1/customers",
        headers=auth_header(client),
        json={"company_name": "노바테크"},
    )

    assert response.status_code == 422


def test_all_endpoints_require_login(client: TestClient) -> None:
    for response in (
        client.post("/api/v1/customers", json=CUSTOMER),
        client.get("/api/v1/customers"),
        client.get("/api/v1/customers/1"),
        client.patch("/api/v1/customers/1", json={"name": "이서연"}),
    ):
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"


def test_list_returns_own_customers_newest_first(client: TestClient) -> None:
    headers = auth_header(client)
    other = auth_header(client, "other@example.com")
    first = create(client, headers, name="첫째").json()["data"]["customer_id"]
    create(client, other, name="남의 고객")
    second = create(client, headers, name="둘째").json()["data"]["customer_id"]

    response = client.get("/api/v1/customers", headers=headers)

    assert response.status_code == 200
    customers = response.json()["data"]["customers"]
    assert [c["customer_id"] for c in customers] == [second, first]
    assert [c["name"] for c in customers] == ["둘째", "첫째"]


def test_list_is_empty_without_customers(client: TestClient) -> None:
    response = client.get("/api/v1/customers", headers=auth_header(client))

    assert response.status_code == 200
    assert response.json()["data"] == {"customers": []}


def test_get_returns_own_customer(client: TestClient) -> None:
    headers = auth_header(client)
    created = create(client, headers).json()["data"]

    response = client.get(
        f"/api/v1/customers/{created['customer_id']}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["data"] == created


def test_unknown_and_other_users_customer_return_the_same_404(
    client: TestClient,
    sessionmaker: async_sessionmaker,
) -> None:
    customer_id = create(client, auth_header(client)).json()["data"]["customer_id"]
    other = auth_header(client, "other@example.com")

    responses = [
        client.get(f"/api/v1/customers/{customer_id}", headers=other),
        client.patch(
            f"/api/v1/customers/{customer_id}",
            headers=other,
            json={"name": "바꿔치기"},
        ),
        client.get(f"/api/v1/customers/{customer_id + 1}", headers=other),
        client.patch(
            f"/api/v1/customers/{customer_id + 1}",
            headers=other,
            json={"name": "바꿔치기"},
        ),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == responses[0].json()
    assert responses[0].json()["code"] == "CUSTOMER_NOT_FOUND"
    [customer] = stored_customers(sessionmaker)
    assert customer.name == CUSTOMER["name"]


@pytest.mark.parametrize("customer_id", ["0", "-1", "abc", str(2**31)])
def test_id_outside_integer_range_is_rejected(
    client: TestClient,
    customer_id: str,
) -> None:
    response = client.get(
        f"/api/v1/customers/{customer_id}",
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_patch_changes_only_given_fields(client: TestClient) -> None:
    headers = auth_header(client)
    created = create(client, headers).json()["data"]

    response = client.patch(
        f"/api/v1/customers/{created['customer_id']}",
        headers=headers,
        json={"department": "전략기획팀", "title": " 이사 "},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        **created,
        "department": "전략기획팀",
        "title": "이사",
        "update_at": data["update_at"],
    }
    assert data["update_at"] >= created["update_at"]
    fetched = client.get(
        f"/api/v1/customers/{created['customer_id']}",
        headers=headers,
    )
    assert fetched.json()["data"] == data


def test_patch_clears_optional_field_with_null_or_blank(client: TestClient) -> None:
    headers = auth_header(client)
    customer_id = create(client, headers).json()["data"]["customer_id"]

    response = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=headers,
        json={"industry": None, "department": ""},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["industry"] is None
    assert data["department"] is None
    assert data["title"] == CUSTOMER["title"]


@pytest.mark.parametrize(
    "payload",
    [
        {"company_name": None},
        {"name": None},
        {"company_name": "  "},
        {"name": ""},
        {"name": "가" * 51},
    ],
)
def test_patch_rejects_invalid_values(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    payload: dict,
) -> None:
    headers = auth_header(client)
    customer_id = create(client, headers).json()["data"]["customer_id"]

    response = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    [customer] = stored_customers(sessionmaker)
    assert customer.company_name == CUSTOMER["company_name"]
    assert customer.name == CUSTOMER["name"]


def test_patch_with_empty_body_changes_nothing(client: TestClient) -> None:
    headers = auth_header(client)
    created = create(client, headers).json()["data"]

    response = client.patch(
        f"/api/v1/customers/{created['customer_id']}",
        headers=headers,
        json={},
    )

    assert response.status_code == 200
    assert response.json()["data"] == created

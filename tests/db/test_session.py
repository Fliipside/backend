import asyncio
from typing import Any

from app.db.session import verify_database_connection


class FakeConnection:
    def __init__(self) -> None:
        self.executed_statement = ""

    async def execute(self, statement: Any) -> None:
        self.executed_statement = str(statement)


class FakeConnectionContextManager:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def connect(self) -> FakeConnectionContextManager:
        return FakeConnectionContextManager(self.connection)


def test_verify_database_connection_executes_select_one() -> None:
    engine = FakeEngine()

    asyncio.run(verify_database_connection(engine))  # type: ignore[arg-type]

    assert engine.connection.executed_statement == "SELECT 1"

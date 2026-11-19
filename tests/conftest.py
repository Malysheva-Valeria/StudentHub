from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from app.utils import local_today

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    return Settings(db_path=str(db_path), session_secret="test-secret", production=False, host="127.0.0.1", port=0)


@pytest.fixture(scope="module")
def app(settings):
    """Fresh demo-seeded database per test module."""
    return create_app(settings)


@pytest.fixture(scope="module")
def db(settings) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.db_path)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def make_client(app) -> Callable[..., TestClient]:
    def _make(username: str | None = None, password: str | None = None) -> TestClient:
        client = TestClient(app)
        if username:
            r = client.post("/api/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, r.text
        return client
    return _make


@pytest.fixture(scope="module")
def anon(make_client) -> TestClient:
    return make_client()


@pytest.fixture(scope="module")
def admin(make_client) -> TestClient:
    return make_client("admin", "admin123")


@pytest.fixture(scope="module")
def teacher(make_client) -> TestClient:
    return make_client("teacher", "teacher123")


@pytest.fixture
def today() -> str:
    return local_today().isoformat()


@pytest.fixture
def fresh_app(tmp_path):
    """Factory for an isolated app with its own database, for tests that mutate global state."""
    def _make(**overrides) -> tuple:
        values = {"db_path": str(tmp_path / "fresh.db"), "session_secret": "fresh-secret", "production": False,
                  "host": "127.0.0.1", "port": 0, **overrides}
        settings = Settings(**values)
        return create_app(settings), settings
    return _make


def login(client: TestClient, username: str, password: str) -> TestClient:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return client

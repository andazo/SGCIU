from __future__ import annotations

import os

import pytest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["REQUIRE_ADMIN_AUTH"] = "false"

from app import models  # noqa: F401
from app.db import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def database_schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

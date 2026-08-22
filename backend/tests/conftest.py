from __future__ import annotations

import os

import pytest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["OPENAI_API_KEY"] = "test-key-not-used"
os.environ["REQUIRE_ADMIN_AUTH"] = "false"

from app import models  # noqa: F401
from app.db import Base, SessionLocal, engine
from tests.fakes import (
    CompleteIntakeProvider,
    LocalEmbeddingDouble,
    LocalIncidentAssessmentDouble,
)


@pytest.fixture(autouse=True)
def isolated_runtime(database_schema, monkeypatch):
    monkeypatch.setattr(
        "app.services.intake.get_intake_provider",
        lambda: CompleteIntakeProvider(),
    )
    monkeypatch.setattr(
        "app.services.semantic.get_embedding_provider",
        lambda settings=None: LocalEmbeddingDouble(),
    )
    monkeypatch.setattr(
        "app.services.reviews.get_incident_assessment_provider",
        lambda settings=None: LocalIncidentAssessmentDouble(),
    )


@pytest.fixture
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

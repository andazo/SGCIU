from collections import Counter

from sqlalchemy import func, select

from app.evaluation.seed_incidents import (
    SYNTHETIC_DATE_END,
    SYNTHETIC_DATE_START,
    load_seed_dataset,
    seed_incidents,
    synthetic_created_at,
)
from app.models import ComplaintSubmission, HumanReview, IncidentEmbedding
from app.tools.incidents import build_incident_tool_registry


def test_flores_dataset_contains_50_diverse_synthetic_cases():
    dataset = load_seed_dataset()

    assert dataset.version == "1.1.0"
    assert len(dataset.incidents) == 50
    assert len({incident.case_id for incident in dataset.incidents}) == 50
    assert Counter(incident.distrito for incident in dataset.incidents) == {
        "San Joaquin": 20,
        "Barrantes": 15,
        "Llorente": 15,
    }
    assert len({incident.categoria_preliminar for incident in dataset.incidents}) >= 12
    assert sum(incident.requires_human_review for incident in dataset.incidents) == 5


def test_seed_is_idempotent_and_indexes_every_incident(db_session):
    dataset = load_seed_dataset()

    first = seed_incidents(db_session, dataset)
    second = seed_incidents(db_session, dataset)

    assert first.created == 50
    assert first.skipped_existing == 0
    assert first.indexed == 50
    assert first.pending_embeddings == 0
    assert second.created == 0
    assert second.skipped_existing == 50
    assert second.indexed == 50
    assert first.dates_normalized == 50
    assert second.dates_normalized == 0
    assert db_session.scalar(select(func.count(ComplaintSubmission.id))) == 50
    assert db_session.scalar(select(func.count(IncidentEmbedding.id))) == 50
    assert db_session.scalar(select(func.count(HumanReview.id))) == 5

    incidents = list(db_session.scalars(select(ComplaintSubmission)))
    assert all(incident.name is None for incident in incidents)
    assert all(incident.email is None for incident in incidents)
    assert all(incident.analysis_metadata["synthetic"] is True for incident in incidents)
    assert all(
        SYNTHETIC_DATE_START
        <= synthetic_created_at(incident.analysis_metadata["synthetic_case_id"])
        <= SYNTHETIC_DATE_END
        for incident in incidents
    )
    assert all(
        incident.created_at.replace(tzinfo=SYNTHETIC_DATE_START.tzinfo)
        == synthetic_created_at(incident.analysis_metadata["synthetic_case_id"])
        for incident in incidents
    )

    aggregate = build_incident_tool_registry().call(
        db_session,
        "aggregate_incidents",
        {
            "group_by": "distrito",
            "district": None,
            "category": None,
            "synthetic_only": True,
        },
        actor_role="admin",
    )
    assert aggregate["total"] == 50
    assert {group["value"]: group["count"] for group in aggregate["groups"]} == {
        "San Joaquin": 20,
        "Barrantes": 15,
        "Llorente": 15,
    }

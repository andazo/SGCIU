from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.evaluation.module_runner import (
    _percentile,
    _persist,
    evaluate_clustering,
    evaluate_intake,
)
from app.evaluation.seed_incidents import DEFAULT_DATASET, load_seed_dataset, seed_incidents
from app.models import EvaluationRun
from tests.fakes import CompleteIntakeProvider


def test_percentile_uses_nearest_rank_for_small_datasets():
    assert _percentile([], 0.95) == 0.0
    assert _percentile([10, 20, 30, 40], 0.5) == 20
    assert _percentile([10, 20, 30, 40], 0.95) == 40


def test_intake_evaluation_reports_all_versioned_synthetic_cases():
    dataset = load_seed_dataset()

    report = evaluate_intake(CompleteIntakeProvider(), dataset, DEFAULT_DATASET)

    assert report.module == "citizen_intake"
    assert report.dataset_version == dataset.version
    assert report.metrics["cases"] == 50
    assert len(report.dataset_sha256) == 64
    assert len(report.case_results) == 50
    assert report.metrics["usage"]["estimated_cost_usd"] == 0.0


def test_evaluation_run_persists_dataset_provenance(db_session):
    dataset = load_seed_dataset()
    report = evaluate_intake(CompleteIntakeProvider(), dataset, DEFAULT_DATASET)
    get_settings.cache_clear()

    record = _persist(db_session, report, get_settings())

    stored = db_session.scalar(select(EvaluationRun).where(EvaluationRun.id == record.id))
    assert stored is not None
    assert stored.module == "citizen_intake"
    assert stored.dataset_sha256 == report.dataset_sha256
    assert stored.metrics["cases"] == 50
    assert stored.started_at.replace(tzinfo=UTC) <= datetime.now(UTC)


def test_clustering_evaluation_uses_explicit_gold_groups_and_threshold_sweep(db_session):
    dataset = load_seed_dataset()
    seed_incidents(db_session, dataset)

    report = evaluate_clustering(db_session, dataset, DEFAULT_DATASET)

    assert report.metrics["expected_pairs"] == 4
    assert report.metrics["gold_pair_definition"].startswith("explicit expert-authored")
    assert set(report.metrics["threshold_analysis"]) == {
        "0.60",
        "0.65",
        "0.70",
        "0.75",
        "0.78",
        "0.80",
        "0.85",
    }

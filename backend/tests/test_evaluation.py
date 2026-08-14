from dataclasses import replace

from app.ai.intake import DeterministicIntakeProvider
from app.config import get_settings
from app.costs import estimate_embedding_cost, estimate_llm_cost
from app.evaluation.metrics import accuracy, macro_f1, recall_at_k, reciprocal_rank
from app.evaluation.runner import evaluate_intake, load_dataset


def test_quality_metrics_cover_classification_and_retrieval():
    assert accuracy(["a", "b"], ["a", "b"]) == 1.0
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert recall_at_k([4, 2, 8], {2, 9}, 2) == 0.5
    assert reciprocal_rank([4, 2, 8], {2}) == 0.5


def test_versioned_intake_dataset_runs_reproducibly():
    report = evaluate_intake(DeterministicIntakeProvider(), load_dataset())

    assert report.dataset_version == "1.0.0"
    assert report.cases == 10
    assert report.classification_accuracy >= 0.9
    assert report.vehicle_entity_f1 == 1.0
    assert report.human_review_recall == 1.0


def test_cost_estimates_use_configured_provider_rates():
    settings = replace(
        get_settings(),
        llm_input_cost_per_million=1.0,
        llm_output_cost_per_million=2.0,
        embedding_cost_per_million=0.5,
    )

    assert estimate_llm_cost(1_000_000, 500_000, settings) == 2.0
    assert estimate_embedding_cost(2_000_000, settings) == 1.0

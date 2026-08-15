from dataclasses import replace

from app.config import _normalize_database_url, get_settings
from app.costs import estimate_embedding_cost, estimate_llm_cost
from app.evaluation.metrics import accuracy, macro_f1, recall_at_k, reciprocal_rank
from app.evaluation.runner import evaluate_intake, load_dataset
from tests.fakes import QueueIntakeProvider, extracted_data, intake_response


def test_quality_metrics_cover_classification_and_retrieval():
    assert accuracy(["a", "b"], ["a", "b"]) == 1.0
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert recall_at_k([4, 2, 8], {2, 9}, 2) == 0.5
    assert reciprocal_rank([4, 2, 8], {2}) == 0.5


def test_versioned_intake_dataset_runs_reproducibly():
    dataset = load_dataset()
    responses = []
    for case in dataset["cases"]:
        expected = case["expected"]
        data = extracted_data(
            descripcion_detallada=case["text"],
            relacion_incidente=expected["relacion_incidente"],
            categoria_preliminar=expected["categoria_preliminar"],
            distrito=expected["distrito"],
            tipo_lugar=expected["tipo_lugar"],
        )
        data.entities.vehicles = case.get("expected_vehicles", [])
        responses.append(
            intake_response(
                data,
                requires_human_review=case.get("expected_human_review", False),
            )
        )
    report = evaluate_intake(QueueIntakeProvider(*responses), dataset)

    assert report.dataset_version == "1.2.0"
    assert report.cases == 12
    assert report.classification_accuracy == 1.0
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


def test_legacy_postgres_url_uses_the_installed_psycopg_driver():
    assert _normalize_database_url("postgresql://user:pass@db/app") == (
        "postgresql+psycopg://user:pass@db/app"
    )

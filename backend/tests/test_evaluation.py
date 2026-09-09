from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from app.config import _normalize_database_url, get_settings
from app.costs import estimate_embedding_cost, estimate_llm_cost, model_price
from app.evaluation.cost_report import build_cost_report, load_cost_scenario
from app.evaluation.legal_rag_runner import (
    LegalRetrievalCase,
    LegalRetrievalDataset,
    evaluate_retrieval,
)
from app.evaluation.metrics import accuracy, entity_scores, macro_f1, recall_at_k, reciprocal_rank
from app.evaluation.runner import evaluate_intake, load_dataset
from tests.fakes import QueueIntakeProvider, extracted_data, intake_response


def test_quality_metrics_cover_classification_and_retrieval():
    assert accuracy(["a", "b"], ["a", "b"]) == 1.0
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert recall_at_k([4, 2, 8], {2, 9}, 2) == 0.5
    assert reciprocal_rank([4, 2, 8], {2}) == 0.5
    assert entity_scores([{"Parque Central"}], [{"parque-central"}])["f1"] == 1.0


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


def test_legal_retrieval_evaluation_reports_hit_rates_and_mrr():
    class RetrievalServiceDouble:
        retriever = SimpleNamespace(
            embedding_provider=SimpleNamespace(model_name="test-embedding")
        )

        def search(self, query, top_k):
            keys = ["document-a", "document-b"] if query == "primera" else [
                "document-b",
                "document-c",
            ]
            return [SimpleNamespace(document_key=key) for key in keys]

    dataset = LegalRetrievalDataset(
        version="test-v1",
        description="Evaluación sintética.",
        cases=[
            LegalRetrievalCase(
                case_id="one",
                query="primera",
                expected_document_keys=["document-a"],
            ),
            LegalRetrievalCase(
                case_id="two",
                query="segunda",
                expected_document_keys=["document-c"],
            ),
        ],
    )

    report = evaluate_retrieval(RetrievalServiceDouble(), dataset)

    assert report.hit_rate_at_1 == 0.5
    assert report.hit_rate_at_3 == 1.0
    assert report.mean_reciprocal_rank == 0.75
    assert report.misses_at_8 == []


def test_cost_estimates_use_configured_provider_rates():
    settings = replace(
        get_settings(),
        llm_input_cost_per_million=1.0,
        llm_output_cost_per_million=2.0,
        embedding_cost_per_million=0.5,
    )

    assert estimate_llm_cost(1_000_000, 500_000, settings) == 2.0
    assert estimate_embedding_cost(2_000_000, settings) == 1.0


def test_cost_estimates_use_model_catalog_when_overrides_are_zero():
    settings = replace(
        get_settings(),
        llm_input_cost_per_million=0.0,
        llm_output_cost_per_million=0.0,
        embedding_cost_per_million=0.0,
    )

    assert estimate_llm_cost(
        1_000_000, 100_000, settings, model_name="gpt-5.6"
    ) == 6.0
    assert estimate_llm_cost(
        1_000_000, 100_000, settings, model_name="gpt-5.4-mini"
    ) == 1.2
    assert estimate_embedding_cost(
        1_000_000, settings, model_name="text-embedding-3-large"
    ) == 0.13
    assert model_price("gpt-5.4-mini-2026-08-01") == model_price("gpt-5.4-mini")


def test_cost_estimates_price_cached_input_and_reject_invalid_usage():
    settings = replace(
        get_settings(),
        llm_input_cost_per_million=0.0,
        llm_output_cost_per_million=0.0,
    )

    assert estimate_llm_cost(
        1_000_000,
        100_000,
        settings,
        model_name="gpt-5.6-terra",
        cached_input_tokens=500_000,
    ) == 2.3
    with pytest.raises(ValueError, match="negativos"):
        estimate_embedding_cost(-1, settings)
    with pytest.raises(ValueError, match="superar"):
        estimate_llm_cost(1, 0, settings, cached_input_tokens=2)
    with pytest.raises(ValueError, match="tarifa completa"):
        estimate_llm_cost(100, 10, settings, model_name="unknown-model")


def test_versioned_cost_scenario_remains_below_warning_budget():
    report = build_cost_report(load_cost_scenario(), as_of=date(2026, 9, 6))

    assert report["scenario_version"] == "1.0.0"
    assert report["pricing_is_current"] is True
    assert report["totals"] == {
        "monthly_ai_usd": 15.9002,
        "monthly_infrastructure_usd": 29.05,
        "monthly_estimate_usd": 44.9502,
        "one_time_ai_usd": 0.3315,
        "monthly_warning_usd": 75.0,
        "within_warning_budget": True,
    }


def test_legacy_postgres_url_uses_the_installed_psycopg_driver():
    assert _normalize_database_url("postgresql://user:pass@db/app") == (
        "postgresql+psycopg://user:pass@db/app"
    )

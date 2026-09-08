"""Run synthetic, versioned quality evaluations and persist their evidence.

This module is deliberately a CLI-only workload. It never accepts user input, and it
requires an explicit confirmation before an evaluation that can call paid models in
production.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.gateway import LocalToolGateway
from app.agents.operational import OperationalAgent
from app.ai.intake import IntakeProvider, get_intake_provider
from app.config import Settings, get_settings
from app.costs import estimate_embedding_cost
from app.db import SessionLocal
from app.evaluation.legal_rag_runner import (
    DEFAULT_DATASET as DEFAULT_RAG_DATASET,
)
from app.evaluation.legal_rag_runner import (
    LegalRetrievalDataset,
)
from app.evaluation.legal_rag_runner import (
    load_dataset as load_rag_dataset,
)
from app.evaluation.metrics import accuracy, entity_scores, macro_f1
from app.evaluation.seed_incidents import (
    DEFAULT_DATASET as DEFAULT_INCIDENT_DATASET,
)
from app.evaluation.seed_incidents import (
    SyntheticIncidentDataset,
    load_seed_dataset,
    seed_incidents,
)
from app.models import (
    ComplaintSubmission,
    EvaluationRun,
    IncidentClusterMember,
    LegalChunk,
    LegalDocument,
)
from app.rag.corpus import LegalCorpusIndexer
from app.schemas import ChatMessage, ComplaintExtractedData, ModelUsage
from app.services.legal_rag import LegalRAGService

DEFAULT_AGENT_DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "agent_cases.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ranked = sorted(values)
    index = max(0, min(len(ranked) - 1, math.ceil(len(ranked) * percentile) - 1))
    return round(ranked[index], 2)


def _usage_totals(usages: list[ModelUsage]) -> dict[str, float | int]:
    return {
        "input_tokens": sum(item.input_tokens for item in usages),
        "output_tokens": sum(item.output_tokens for item in usages),
        "estimated_cost_usd": round(sum(item.estimated_cost_usd for item in usages), 8),
        "estimated_cost_per_case_usd": round(
            sum(item.estimated_cost_usd for item in usages) / len(usages), 8
        )
        if usages
        else 0.0,
    }


def _binary_scores(expected: list[bool], predicted: list[bool]) -> dict[str, float]:
    true_positive = sum(left and right for left, right in zip(expected, predicted, strict=True))
    false_positive = sum(
        not left and right for left, right in zip(expected, predicted, strict=True)
    )
    false_negative = sum(
        left and not right for left, right in zip(expected, predicted, strict=True)
    )
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


@dataclass(frozen=True, slots=True)
class ModuleReport:
    module: str
    dataset_name: str
    dataset_version: str
    dataset_sha256: str
    started_at: datetime
    completed_at: datetime
    metrics: dict[str, Any]
    case_results: list[dict[str, Any]]


def _persist(db: Session, report: ModuleReport, settings: Settings) -> EvaluationRun:
    record = EvaluationRun(
        module=report.module,
        dataset_name=report.dataset_name,
        dataset_version=report.dataset_version,
        dataset_sha256=report.dataset_sha256,
        environment=settings.app_env,
        model_configuration={
            "intake_model": settings.openai_intake_model,
            "operational_model": settings.openai_model,
            "legal_rag_model": settings.legal_rag_model,
            "embedding_model": settings.openai_embedding_model,
            "legal_embedding_model": settings.legal_rag_embedding_model,
        },
        metrics=report.metrics,
        case_results=report.case_results,
        started_at=report.started_at,
        completed_at=report.completed_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def evaluate_intake(
    provider: IntakeProvider,
    dataset: SyntheticIncidentDataset,
    dataset_path: Path,
) -> ModuleReport:
    started_at = datetime.now(UTC)
    expected_categories: list[str] = []
    predicted_categories: list[str] = []
    expected_relations: list[str] = []
    predicted_relations: list[str] = []
    expected_districts: list[str] = []
    predicted_districts: list[str] = []
    expected_places: list[str] = []
    predicted_places: list[str] = []
    expected_entities: list[set[str]] = []
    predicted_entities: list[set[str]] = []
    expected_reviews: list[bool] = []
    predicted_reviews: list[bool] = []
    latencies: list[float] = []
    usages: list[ModelUsage] = []
    cases: list[dict[str, Any]] = []

    for record in dataset.incidents:
        started = time.perf_counter()
        response = provider.analyze(
            [ChatMessage(role="user", content=record.descripcion_detallada)],
            ComplaintExtractedData(),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = provider.last_usage
        expected_categories.append(record.categoria_preliminar)
        predicted_categories.append(response.extracted_data.categoria_preliminar or "missing")
        expected_relations.append(record.relacion_incidente)
        predicted_relations.append(response.extracted_data.relacion_incidente or "missing")
        expected_districts.append(record.distrito)
        predicted_districts.append(response.extracted_data.distrito or "missing")
        expected_places.append(record.tipo_lugar)
        predicted_places.append(response.extracted_data.tipo_lugar or "missing")
        expected_entities.append(set(record.vehicles + record.objects + record.establishments))
        predicted_entities.append(
            set(
                response.extracted_data.entities.vehicles
                + response.extracted_data.entities.objects
                + response.extracted_data.entities.establishments
            )
        )
        expected_reviews.append(record.requires_human_review)
        predicted_reviews.append(response.requires_human_review)
        latencies.append(latency_ms)
        usages.append(usage)
        cases.append(
            {
                "case_id": record.case_id,
                "latency_ms": latency_ms,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "estimated_cost_usd": usage.estimated_cost_usd,
                "expected_category": record.categoria_preliminar,
                "predicted_category": response.extracted_data.categoria_preliminar,
                "expected_district": record.distrito,
                "predicted_district": response.extracted_data.distrito,
                "expected_human_review": record.requires_human_review,
                "predicted_human_review": response.requires_human_review,
                "is_complete": response.is_complete,
            }
        )

    metrics: dict[str, Any] = {
        "cases": len(cases),
        "category_accuracy": round(accuracy(expected_categories, predicted_categories), 4),
        "category_macro_f1": round(macro_f1(expected_categories, predicted_categories), 4),
        "field_accuracy": {
            "relation": round(accuracy(expected_relations, predicted_relations), 4),
            "district": round(accuracy(expected_districts, predicted_districts), 4),
            "place_type": round(accuracy(expected_places, predicted_places), 4),
        },
        "entities": entity_scores(expected_entities, predicted_entities),
        "human_review": _binary_scores(expected_reviews, predicted_reviews),
        "completion_rate": round(sum(case["is_complete"] for case in cases) / len(cases), 4),
        "latency_ms": {
            "average": round(sum(latencies) / len(latencies), 2),
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
        "usage": _usage_totals(usages),
    }
    return ModuleReport(
        module="citizen_intake",
        dataset_name=dataset_path.name,
        dataset_version=dataset.version,
        dataset_sha256=_sha256(dataset_path),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        metrics=metrics,
        case_results=cases,
    )


def evaluate_legal_rag(
    db: Session,
    dataset: LegalRetrievalDataset,
    dataset_path: Path,
) -> ModuleReport:
    started_at = datetime.now(UTC)
    service = LegalRAGService(db)
    hit_at = {1: 0, 3: 0, 8: 0}
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    usages: list[ModelUsage] = []
    cases: list[dict[str, Any]] = []
    for case in dataset.cases:
        started = time.perf_counter()
        response = service.answer(case.query, audience="administrative")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        retrieved = [citation.document_key for citation in response.citations]
        expected = set(case.expected_document_keys)
        rank = next((index for index, key in enumerate(retrieved, 1) if key in expected), None)
        for limit in hit_at:
            if set(retrieved[:limit]) & expected:
                hit_at[limit] += 1
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        latencies.append(latency_ms)
        usages.append(response.usage)
        cases.append(
            {
                "case_id": case.case_id,
                "latency_ms": latency_ms,
                "expected_documents": sorted(expected),
                "retrieved_documents": retrieved,
                "first_relevant_rank": rank,
                "insufficient_evidence": response.insufficient_evidence,
                "citation_count": len(response.citations),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "estimated_cost_usd": response.usage.estimated_cost_usd,
            }
        )
    total = len(cases)
    citation_valid = sum(
        bool(set(case["retrieved_documents"]) & set(case["expected_documents"])) for case in cases
    )
    return ModuleReport(
        module="legal_rag",
        dataset_name=dataset_path.name,
        dataset_version=dataset.version,
        dataset_sha256=_sha256(dataset_path),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        metrics={
            "cases": total,
            "hit_rate_at_1": round(hit_at[1] / total, 4),
            "hit_rate_at_3": round(hit_at[3] / total, 4),
            "hit_rate_at_8": round(hit_at[8] / total, 4),
            "mean_reciprocal_rank": round(sum(reciprocal_ranks) / total, 4),
            "citation_relevance_rate": round(citation_valid / total, 4),
            "grounded_response_rate": round(
                sum(
                    not case["insufficient_evidence"] and case["citation_count"] > 0
                    for case in cases
                )
                / total,
                4,
            ),
            "latency_ms": {
                "average": round(sum(latencies) / total, 2),
                "p50": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
            },
            "usage": _usage_totals(usages),
        },
        case_results=cases,
    )


def evaluate_clustering(
    db: Session,
    dataset: SyntheticIncidentDataset,
    dataset_path: Path,
) -> ModuleReport:
    started_at = datetime.now(UTC)
    incidents = list(
        db.scalars(
            select(ComplaintSubmission).where(
                ComplaintSubmission.analysis_metadata["source"].as_string()
                == "flores_synthetic_admin_seed"
            )
        )
    )
    by_case = {
        str((incident.analysis_metadata or {}).get("synthetic_case_id")): incident
        for incident in incidents
    }
    expected_groups: dict[str, set[int]] = {}
    for record in dataset.incidents:
        incident = by_case.get(record.case_id)
        if incident is None:
            continue
        expected_groups.setdefault(
            f"{record.distrito}:{record.categoria_preliminar}", set()
        ).add(incident.id)
    expected_pairs = {
        tuple(sorted((left, right)))
        for members in expected_groups.values()
        for left in members
        for right in members
        if left < right
    }
    memberships = list(
        db.execute(select(IncidentClusterMember.cluster_id, IncidentClusterMember.incident_id))
    )
    actual_groups: dict[int, set[int]] = {}
    synthetic_ids = {incident.id for incident in by_case.values()}
    for cluster_id, incident_id in memberships:
        if incident_id in synthetic_ids:
            actual_groups.setdefault(cluster_id, set()).add(incident_id)
    actual_pairs = {
        tuple(sorted((left, right)))
        for members in actual_groups.values()
        for left in members
        for right in members
        if left < right
    }
    true_positive = len(expected_pairs & actual_pairs)
    precision = true_positive / len(actual_pairs) if actual_pairs else 0.0
    recall = true_positive / len(expected_pairs) if expected_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ModuleReport(
        module="semantic_clustering",
        dataset_name=dataset_path.name,
        dataset_version=dataset.version,
        dataset_sha256=_sha256(dataset_path),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        metrics={
            "incidents_evaluated": len(by_case),
            "gold_pair_definition": "same synthetic district and preliminary category",
            "expected_pairs": len(expected_pairs),
            "retrieved_pairs": len(actual_pairs),
            "pairwise_precision": round(precision, 4),
            "pairwise_recall": round(recall, 4),
            "pairwise_f1": round(f1, 4),
            "clusters_with_synthetic_members": len(actual_groups),
            "latency_ms": round((datetime.now(UTC) - started_at).total_seconds() * 1000, 2),
            "usage": _usage_totals([]),
        },
        case_results=[
            {
                "cluster_id": cluster_id,
                "synthetic_incident_ids": sorted(members),
                "member_count": len(members),
            }
            for cluster_id, members in sorted(actual_groups.items())
        ],
    )


def evaluate_indexing(db: Session, settings: Settings) -> ModuleReport:
    started_at = datetime.now(UTC)
    result = LegalCorpusIndexer(db, settings).index_all(force=False)
    estimated_tokens = int(
        db.scalar(select(func.coalesce(func.sum(LegalChunk.estimated_tokens), 0))) or 0
    )
    initial_cost = estimate_embedding_cost(
        estimated_tokens,
        settings,
        model_name=settings.legal_rag_embedding_model,
    )
    report_path = settings.legal_rag_corpus_path / "manifest.json"
    return ModuleReport(
        module="legal_indexing",
        dataset_name=report_path.name,
        dataset_version=result.corpus_version,
        dataset_sha256=_sha256(report_path),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        metrics={
            **result.model_dump(),
            "indexed_documents_in_database": int(
                db.scalar(select(func.count(LegalDocument.id))) or 0
            ),
            "indexed_chunks_in_database": int(db.scalar(select(func.count(LegalChunk.id))) or 0),
            "estimated_tokens_for_full_corpus": estimated_tokens,
            "estimated_one_time_embedding_cost_usd": initial_cost,
            "latency_ms": round((datetime.now(UTC) - started_at).total_seconds() * 1000, 2),
            "idempotent": result.embeddings_created == 0 and result.documents_failed == 0,
        },
        case_results=[],
    )


def _load_agent_cases(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("version"), str) or not isinstance(payload.get("cases"), list):
        raise ValueError("El dataset del agente debe contener version y cases.")
    return payload


async def evaluate_operational_agent(
    db: Session,
    dataset_path: Path,
    settings: Settings,
) -> ModuleReport:
    dataset = _load_agent_cases(dataset_path)
    started_at = datetime.now(UTC)
    agent = OperationalAgent(LocalToolGateway(db), settings)
    latencies: list[float] = []
    usages: list[ModelUsage] = []
    cases: list[dict[str, Any]] = []
    for case in dataset["cases"]:
        started = time.perf_counter()
        response = await agent.run(str(case["query"]))
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        expected_tools = set(case["expected_tools"])
        actual_tools = {step.tool_name for step in response.steps if step.success}
        latencies.append(latency_ms)
        usages.append(response.usage)
        cases.append(
            {
                "case_id": case["case_id"],
                "latency_ms": latency_ms,
                "expected_tools": sorted(expected_tools),
                "actual_tools": sorted(actual_tools),
                "tool_expectation_met": expected_tools.issubset(actual_tools),
                "successful_tool_steps": sum(step.success for step in response.steps),
                "total_tool_steps": len(response.steps),
                "has_evidence": bool(response.incident_citations or response.legal_citations),
                "requires_human_review": response.requires_human_review,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "estimated_cost_usd": response.usage.estimated_cost_usd,
            }
        )
    total = len(cases)
    return ModuleReport(
        module="operational_agent",
        dataset_name=dataset_path.name,
        dataset_version=dataset["version"],
        dataset_sha256=_sha256(dataset_path),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        metrics={
            "cases": total,
            "tool_selection_success_rate": round(
                sum(case["tool_expectation_met"] for case in cases) / total, 4
            ),
            "evidence_rate": round(sum(case["has_evidence"] for case in cases) / total, 4),
            "successful_tool_step_rate": round(
                sum(case["successful_tool_steps"] for case in cases)
                / max(1, sum(case["total_tool_steps"] for case in cases)),
                4,
            ),
            "latency_ms": {
                "average": round(sum(latencies) / total, 2),
                "p50": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
            },
            "usage": _usage_totals(usages),
        },
        case_results=cases,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta métricas reproducibles por módulo.")
    parser.add_argument(
        "--modules",
        nargs="+",
        choices=["all", "intake", "rag", "agent", "clustering", "indexing"],
        default=["all"],
    )
    parser.add_argument("--incident-dataset", type=Path, default=DEFAULT_INCIDENT_DATASET)
    parser.add_argument("--agent-dataset", type=Path, default=DEFAULT_AGENT_DATASET)
    parser.add_argument("--seed-incidents", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.is_production and not args.confirm_production:
        parser.error("En producción debe especificar --confirm-production.")
    modules = {"intake", "rag", "agent", "clustering", "indexing"}
    selected = modules if "all" in args.modules else set(args.modules)
    incident_dataset = load_seed_dataset(args.incident_dataset)
    reports: list[ModuleReport] = []
    with SessionLocal() as db:
        seed_result = None
        if args.seed_incidents:
            seed_result = seed_incidents(db, incident_dataset, ensure_semantic_index=True)
        if "intake" in selected:
            reports.append(
                evaluate_intake(
                    get_intake_provider(settings),
                    incident_dataset,
                    args.incident_dataset,
                )
            )
        if "rag" in selected:
            reports.append(
                evaluate_legal_rag(
                    db,
                    load_rag_dataset(DEFAULT_RAG_DATASET),
                    DEFAULT_RAG_DATASET,
                )
            )
        if "agent" in selected:
            reports.append(
                asyncio.run(evaluate_operational_agent(db, args.agent_dataset, settings))
            )
        if "clustering" in selected:
            reports.append(evaluate_clustering(db, incident_dataset, args.incident_dataset))
        if "indexing" in selected:
            reports.append(evaluate_indexing(db, settings))
        persisted = [_persist(db, report, settings) for report in reports]
    print(
        json.dumps(
            {
                "seed": asdict(seed_result) if seed_result else None,
                "evaluation_run_ids": [record.id for record in persisted],
                "reports": [asdict(report) for report in reports],
                "git_revision": os.getenv("K_REVISION") or os.getenv("COMMIT_SHA") or "unknown",
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()

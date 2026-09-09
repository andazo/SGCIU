from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import AdminRole
from app.db import get_db
from app.models import AIInteractionTrace, ManualEvaluationLabel
from app.schemas import AIInteractionTraceResponse, ManualEvaluationLabelRequest
from app.services.normalization import canonical_category, canonical_district

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
DbSession = Annotated[Session, Depends(get_db)]


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ranked = sorted(values)
    index = max(0, min(len(ranked) - 1, math.ceil(len(ranked) * percentile) - 1))
    return round(ranked[index], 2)


def _serialize(
    trace: AIInteractionTrace,
    label: ManualEvaluationLabel | None,
) -> AIInteractionTraceResponse:
    response = AIInteractionTraceResponse.model_validate(trace)
    if label is None:
        return response
    return response.model_copy(
        update={
            "manual_label": {
                "expected_output": label.expected_output,
                "quality_scores": label.quality_scores,
                "notes": label.notes,
            }
        }
    )


def _field_matches(field: str, expected: object, actual: object) -> bool:
    if field == "district":
        return canonical_district(str(expected)) == canonical_district(str(actual))
    if field == "category":
        return canonical_category(str(expected)) == canonical_category(str(actual))
    return expected == actual


@router.get("/interactions", response_model=list[AIInteractionTraceResponse])
def list_interactions(
    db: DbSession,
    _actor: AdminRole,
    feature: str | None = None,
    session_id: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    query = select(AIInteractionTrace).order_by(AIInteractionTrace.created_at.desc())
    if feature:
        query = query.where(AIInteractionTrace.feature == feature)
    if session_id:
        query = query.where(AIInteractionTrace.session_id == session_id)
    if created_from:
        query = query.where(
            AIInteractionTrace.created_at >= datetime.combine(created_from, time.min, tzinfo=UTC)
        )
    if created_to:
        query = query.where(
            AIInteractionTrace.created_at
            < datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    traces = list(db.scalars(query.limit(limit)))
    labels = (
        {
            label.trace_id: label
            for label in db.scalars(
                select(ManualEvaluationLabel).where(
                    ManualEvaluationLabel.trace_id.in_([trace.trace_id for trace in traces])
                )
            )
        }
        if traces
        else {}
    )
    return [_serialize(trace, labels.get(trace.trace_id)) for trace in traces]


@router.put(
    "/interactions/{trace_id}/label",
    response_model=AIInteractionTraceResponse,
)
def label_interaction(
    trace_id: str,
    payload: ManualEvaluationLabelRequest,
    db: DbSession,
    _actor: AdminRole,
):
    trace = db.scalar(select(AIInteractionTrace).where(AIInteractionTrace.trace_id == trace_id))
    if trace is None:
        raise HTTPException(status_code=404, detail="Traza de interacción no encontrada.")
    label = db.scalar(
        select(ManualEvaluationLabel).where(ManualEvaluationLabel.trace_id == trace_id)
    )
    if label is None:
        label = ManualEvaluationLabel(trace_id=trace_id)
        db.add(label)
    label.expected_output = payload.expected_output
    label.quality_scores = payload.quality_scores
    label.notes = payload.notes
    db.commit()
    db.refresh(label)
    return _serialize(trace, label)


@router.get("/summary", response_model=dict[str, object])
def evaluation_summary(
    db: DbSession,
    _actor: AdminRole,
    created_from: date | None = None,
    created_to: date | None = None,
):
    query = select(AIInteractionTrace).order_by(AIInteractionTrace.created_at)
    if created_from:
        query = query.where(
            AIInteractionTrace.created_at >= datetime.combine(created_from, time.min, tzinfo=UTC)
        )
    if created_to:
        query = query.where(
            AIInteractionTrace.created_at
            < datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    traces = list(db.scalars(query))
    labels = (
        list(
            db.scalars(
                select(ManualEvaluationLabel).where(
                    ManualEvaluationLabel.trace_id.in_([trace.trace_id for trace in traces])
                )
            )
        )
        if traces
        else []
    )
    traces_by_id = {trace.trace_id: trace for trace in traces}
    by_feature: dict[str, list[AIInteractionTrace]] = {}
    for trace in traces:
        by_feature.setdefault(trace.feature, []).append(trace)
    quality_values: dict[str, list[float]] = {}
    for label in labels:
        for name, score in (label.quality_scores or {}).items():
            quality_values.setdefault(name, []).append(float(score))
    field_results: dict[str, list[bool]] = {}
    rag_cases: list[tuple[list[str], set[str]]] = []
    tool_cases: list[bool] = []
    for label in labels:
        trace = traces_by_id.get(label.trace_id)
        if trace is None:
            continue
        expected = label.expected_output or {}
        actual = trace.result_metadata or {}
        for field in ("category", "district", "relation", "place_type"):
            if field in expected:
                field_results.setdefault(field, []).append(
                    _field_matches(field, expected[field], actual.get(field))
                )
        expected_documents = expected.get("expected_document_keys")
        if isinstance(expected_documents, list):
            rag_cases.append(
                (
                    [str(value) for value in actual.get("retrieved_document_keys", [])],
                    {str(value) for value in expected_documents},
                )
            )
        expected_tools = expected.get("expected_tool_names")
        if isinstance(expected_tools, list):
            tool_cases.append(
                set(map(str, expected_tools)).issubset(
                    set(map(str, actual.get("tool_names", [])))
                )
            )
    intake_traces = [trace for trace in traces if trace.feature == "citizen_intake"]
    tool_steps = sum(
        int((trace.result_metadata or {}).get("tool_successes", 0))
        + int((trace.result_metadata or {}).get("tool_failures", 0))
        for trace in traces
        if trace.feature == "operational_agent"
    )
    successful_tool_steps = sum(
        int((trace.result_metadata or {}).get("tool_successes", 0))
        for trace in traces
        if trace.feature == "operational_agent"
    )
    return {
        "interactions": len(traces),
        "labeled_interactions": len(labels),
        "input_tokens": sum(trace.input_tokens for trace in traces),
        "output_tokens": sum(trace.output_tokens for trace in traces),
        "estimated_cost_usd": round(sum(trace.estimated_cost_usd for trace in traces), 8),
        "quality_score_averages": {
            name: round(sum(values) / len(values), 4)
            for name, values in sorted(quality_values.items())
        },
        "quality_metrics": {
            "intake_field_accuracy": {
                field: round(sum(results) / len(results), 4)
                for field, results in sorted(field_results.items())
            },
            "intake_completion_rate": round(
                sum(
                    bool((trace.result_metadata or {}).get("is_complete"))
                    for trace in intake_traces
                )
                / len(intake_traces),
                4,
            )
            if intake_traces
            else 0.0,
            "rag_hit_rate_at_1": round(
                sum(bool(set(retrieved[:1]) & expected) for retrieved, expected in rag_cases)
                / len(rag_cases),
                4,
            )
            if rag_cases
            else 0.0,
            "rag_hit_rate_at_3": round(
                sum(bool(set(retrieved[:3]) & expected) for retrieved, expected in rag_cases)
                / len(rag_cases),
                4,
            )
            if rag_cases
            else 0.0,
            "rag_hit_rate_at_8": round(
                sum(bool(set(retrieved[:8]) & expected) for retrieved, expected in rag_cases)
                / len(rag_cases),
                4,
            )
            if rag_cases
            else 0.0,
            "operational_tool_selection_rate": round(
                sum(tool_cases) / len(tool_cases), 4
            )
            if tool_cases
            else 0.0,
            "operational_tool_step_success_rate": round(
                successful_tool_steps / tool_steps, 4
            )
            if tool_steps
            else 0.0,
        },
        "features": {
            feature: {
                "interactions": len(items),
                "success_rate": round(sum(item.success for item in items) / len(items), 4),
                "latency_ms": {
                    "average": round(sum(item.latency_ms for item in items) / len(items), 2),
                    "p50": _nearest_rank([item.latency_ms for item in items], 0.5),
                    "p95": _nearest_rank([item.latency_ms for item in items], 0.95),
                },
                "estimated_cost_usd": round(sum(item.estimated_cost_usd for item in items), 8),
            }
            for feature, items in sorted(by_feature.items())
        },
    }

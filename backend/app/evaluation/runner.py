from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.ai.intake import IntakeProvider, get_intake_provider
from app.evaluation.metrics import accuracy, entity_scores, label_distribution, macro_f1
from app.schemas import ChatMessage, ComplaintExtractedData

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "intake_cases.json"
EVALUATED_FIELDS = (
    "relacion_incidente",
    "categoria_preliminar",
    "distrito",
    "tipo_lugar",
)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    dataset_version: str
    provider: str
    cases: int
    classification_accuracy: float
    classification_macro_f1: float
    field_accuracy: dict[str, float]
    vehicle_entity_precision: float
    vehicle_entity_recall: float
    vehicle_entity_f1: float
    human_review_recall: float
    average_latency_ms: float
    p95_latency_ms: float
    category_distribution: dict[str, int]


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_intake(
    provider: IntakeProvider,
    dataset: dict[str, object],
) -> EvaluationReport:
    cases = dataset["cases"]
    predictions = []
    latencies = []
    for case in cases:
        started = time.perf_counter()
        result = provider.analyze(
            [ChatMessage(role="user", content=case["text"])],
            ComplaintExtractedData(),
        )
        latencies.append((time.perf_counter() - started) * 1000)
        predictions.append(result)

    expected_categories = [case["expected"]["categoria_preliminar"] for case in cases]
    predicted_categories = [result.extracted_data.categoria_preliminar for result in predictions]
    field_accuracy = {
        field: accuracy(
            [case["expected"][field] for case in cases],
            [getattr(result.extracted_data, field) for result in predictions],
        )
        for field in EVALUATED_FIELDS
    }
    vehicles = entity_scores(
        [set(case.get("expected_vehicles", [])) for case in cases],
        [set(result.extracted_data.entities.vehicles) for result in predictions],
    )
    review_cases = [
        index for index, case in enumerate(cases) if case.get("expected_human_review", False)
    ]
    review_recall = (
        sum(predictions[index].requires_human_review for index in review_cases) / len(review_cases)
        if review_cases
        else 0.0
    )
    sorted_latencies = sorted(latencies)
    p95_index = max(
        0,
        min(len(sorted_latencies) - 1, math.ceil(len(sorted_latencies) * 0.95) - 1),
    )
    return EvaluationReport(
        dataset_version=str(dataset["version"]),
        provider=provider.model_name,
        cases=len(cases),
        classification_accuracy=accuracy(expected_categories, predicted_categories),
        classification_macro_f1=macro_f1(expected_categories, predicted_categories),
        field_accuracy=field_accuracy,
        vehicle_entity_precision=vehicles["precision"],
        vehicle_entity_recall=vehicles["recall"],
        vehicle_entity_f1=vehicles["f1"],
        human_review_recall=review_recall,
        average_latency_ms=sum(latencies) / len(latencies),
        p95_latency_ms=sorted_latencies[p95_index],
        category_distribution=label_distribution(expected_categories),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa el workflow de intake de SGCIU")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    provider = get_intake_provider()
    report = evaluate_intake(provider, load_dataset(args.dataset))
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

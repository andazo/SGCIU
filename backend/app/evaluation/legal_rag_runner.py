from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import Field

from app.db import SessionLocal
from app.schemas import StrictModel
from app.services.legal_rag import LegalRAGService

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "legal_rag_cases.json"


class LegalRetrievalCase(StrictModel):
    case_id: str
    query: str = Field(min_length=3)
    expected_document_keys: list[str] = Field(min_length=1)


class LegalRetrievalDataset(StrictModel):
    version: str
    description: str
    cases: list[LegalRetrievalCase] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class LegalRetrievalReport:
    dataset_version: str
    embedding_model: str
    cases: int
    hit_rate_at_1: float
    hit_rate_at_3: float
    hit_rate_at_8: float
    mean_reciprocal_rank: float
    average_latency_ms: float
    misses_at_8: list[str]


def load_dataset(path: Path = DEFAULT_DATASET) -> LegalRetrievalDataset:
    return LegalRetrievalDataset.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_retrieval(
    service: LegalRAGService,
    dataset: LegalRetrievalDataset,
) -> LegalRetrievalReport:
    hits = {1: 0, 3: 0, 8: 0}
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    misses: list[str] = []
    for case in dataset.cases:
        started = time.perf_counter()
        citations = service.search(case.query, top_k=8)
        latencies.append((time.perf_counter() - started) * 1000)
        retrieved = [citation.document_key for citation in citations]
        expected = set(case.expected_document_keys)
        for k in hits:
            if set(retrieved[:k]) & expected:
                hits[k] += 1
        rank = next(
            (position for position, key in enumerate(retrieved, start=1) if key in expected),
            None,
        )
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        if rank is None:
            misses.append(case.case_id)
    total = len(dataset.cases)
    return LegalRetrievalReport(
        dataset_version=dataset.version,
        embedding_model=service.retriever.embedding_provider.model_name,
        cases=total,
        hit_rate_at_1=hits[1] / total,
        hit_rate_at_3=hits[3] / total,
        hit_rate_at_8=hits[8] / total,
        mean_reciprocal_rank=sum(reciprocal_ranks) / total,
        average_latency_ms=sum(latencies) / total,
        misses_at_8=misses,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa la recuperación del RAG legal de SGCIU")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    with SessionLocal() as db:
        service = LegalRAGService(db)
        report = evaluate_retrieval(service, load_dataset(args.dataset))
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

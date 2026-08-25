from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embeddings import EmbeddingProvider, get_legal_embedding_provider
from app.config import Settings, get_settings
from app.models import LegalChunk, LegalDocument

SPANISH_STOP_WORDS = {
    "a",
    "al",
    "como",
    "con",
    "cual",
    "de",
    "del",
    "el",
    "en",
    "es",
    "esta",
    "la",
    "las",
    "lo",
    "los",
    "para",
    "por",
    "que",
    "se",
    "si",
    "su",
    "un",
    "una",
    "y",
}


@dataclass(frozen=True, slots=True)
class RetrievedLegalSource:
    source_id: str
    chunk: LegalChunk
    document: LegalDocument
    semantic_score: float
    lexical_score: float
    fusion_score: float


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 1 and token not in SPANISH_STOP_WORDS
    ]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return dot / (left_norm * right_norm)


def _bm25(query: str, rows: list[tuple[int, str]]) -> dict[int, float]:
    query_terms = _tokens(query)
    if not query_terms or not rows:
        return {}
    documents = {chunk_id: _tokens(content) for chunk_id, content in rows}
    average_length = sum(len(tokens) for tokens in documents.values()) / len(documents) or 1.0
    frequencies = Counter(
        term for term in set(query_terms) for tokens in documents.values() if term in tokens
    )
    scores: dict[int, float] = {}
    total_documents = len(documents)
    k1 = 1.5
    b = 0.75
    for chunk_id, tokens in documents.items():
        counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = counts[term]
            if not frequency:
                continue
            document_frequency = frequencies[term]
            inverse_frequency = math.log(
                1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * (len(tokens) / average_length)
            )
            score += inverse_frequency * (frequency * (k1 + 1)) / denominator
        if score > 0:
            scores[chunk_id] = score
    return scores


class HybridLegalRetriever:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider or get_legal_embedding_provider(self.settings)

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_keys: list[str] | None = None,
    ) -> list[RetrievedLegalSource]:
        top_k = min(top_k or self.settings.legal_rag_top_k, 20)
        candidate_k = max(top_k, self.settings.legal_rag_candidate_k)
        query_vector = self.embedding_provider.embed(query)
        filters = [
            LegalDocument.status == "active",
            LegalChunk.embedding_model == self.embedding_provider.model_name,
        ]
        if document_keys:
            filters.append(LegalDocument.document_key.in_(document_keys))
        semantic_scores = self._semantic_candidates(query_vector, filters, candidate_k)
        lexical_rows = list(
            self.db.execute(
                select(LegalChunk.id, LegalChunk.content)
                .join(LegalDocument)
                .where(*filters)
            ).all()
        )
        raw_lexical = _bm25(query, lexical_rows)
        lexical_scores = dict(
            sorted(raw_lexical.items(), key=lambda item: item[1], reverse=True)[:candidate_k]
        )
        semantic_rank = {
            chunk_id: rank
            for rank, (chunk_id, _) in enumerate(
                sorted(semantic_scores.items(), key=lambda item: item[1], reverse=True), start=1
            )
        }
        lexical_rank = {
            chunk_id: rank
            for rank, (chunk_id, _) in enumerate(
                sorted(lexical_scores.items(), key=lambda item: item[1], reverse=True), start=1
            )
        }
        max_lexical = max(lexical_scores.values(), default=1.0)
        fusion: dict[int, float] = {}
        for chunk_id in semantic_scores.keys() | lexical_scores.keys():
            score = 0.0
            if chunk_id in semantic_rank:
                score += 0.65 / (60 + semantic_rank[chunk_id])
            if chunk_id in lexical_rank:
                score += 0.35 / (60 + lexical_rank[chunk_id])
            fusion[chunk_id] = score
        if not fusion:
            return []
        candidates = list(
            self.db.execute(
                select(LegalChunk, LegalDocument)
                .join(LegalDocument)
                .where(LegalChunk.id.in_(fusion))
            ).all()
        )
        by_id = {chunk.id: (chunk, document) for chunk, document in candidates}
        ranked_ids = sorted(
            fusion,
            key=lambda chunk_id: (
                fusion[chunk_id],
                -by_id[chunk_id][1].priority if chunk_id in by_id else -9,
            ),
            reverse=True,
        )
        selected: list[RetrievedLegalSource] = []
        content_hashes: set[str] = set()
        per_document: Counter[int] = Counter()
        for chunk_id in ranked_ids:
            if chunk_id not in by_id:
                continue
            semantic = semantic_scores.get(chunk_id, 0.0)
            lexical = lexical_scores.get(chunk_id, 0.0)
            if semantic < self.settings.legal_rag_min_semantic_score and lexical <= 0:
                continue
            chunk, document = by_id[chunk_id]
            if chunk.content_hash in content_hashes or per_document[document.id] >= 3:
                continue
            content_hashes.add(chunk.content_hash)
            per_document[document.id] += 1
            selected.append(
                RetrievedLegalSource(
                    source_id=f"F{len(selected) + 1}",
                    chunk=chunk,
                    document=document,
                    semantic_score=round(semantic, 6),
                    lexical_score=round(lexical / max_lexical, 6),
                    fusion_score=round(fusion[chunk_id] * 61, 6),
                )
            )
            if len(selected) >= top_k:
                break
        return selected

    def _semantic_candidates(
        self,
        query_vector: list[float],
        filters: list[object],
        candidate_k: int,
    ) -> dict[int, float]:
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            distance = LegalChunk.embedding.cosine_distance(query_vector)
            rows = self.db.execute(
                select(LegalChunk.id, distance.label("distance"))
                .join(LegalDocument)
                .where(*filters)
                .order_by(distance)
                .limit(candidate_k)
            ).all()
            return {chunk_id: 1.0 - float(distance_value) for chunk_id, distance_value in rows}
        rows = self.db.execute(
            select(LegalChunk.id, LegalChunk.embedding)
            .join(LegalDocument)
            .where(*filters)
        ).all()
        scores = {
            chunk_id: _cosine(list(embedding), query_vector)
            for chunk_id, embedding in rows
            if embedding
        }
        return dict(
            sorted(scores.items(), key=lambda item: item[1], reverse=True)[:candidate_k]
        )

    def indexed_embedding_count(self) -> int:
        return self.db.scalar(
            select(func.count(LegalChunk.id))
            .join(LegalDocument)
            .where(
                LegalDocument.status == "active",
                LegalChunk.embedding_model == self.embedding_provider.model_name,
            )
        ) or 0


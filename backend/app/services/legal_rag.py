from __future__ import annotations

import hashlib
import time
import uuid

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AuditEvent, LegalQueryTrace
from app.rag.corpus import LegalCorpusIndexer, load_manifest
from app.rag.generation import (
    LEGAL_RAG_PROMPT_VERSION,
    LegalAnswerProvider,
    get_legal_answer_provider,
)
from app.rag.retrieval import HybridLegalRetriever, RetrievedLegalSource
from app.schemas import LegalCitation, LegalFinding, LegalQueryResponse

CLASSIFICATION_LABELS = {
    "legal_obligation": "Obligación legal",
    "municipal_authority": "Facultad municipal",
    "recommended_procedure": "Procedimiento recomendado",
}


def _excerpt(value: str, limit: int = 500) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def source_to_citation(source: RetrievedLegalSource) -> LegalCitation:
    metadata = source.document.document_metadata or {}
    return LegalCitation(
        source_id=source.source_id,
        chunk_id=source.chunk.id,
        document_key=source.document.document_key,
        document_title=source.document.title,
        source_filename=source.document.source_filename,
        pdf_page=source.chunk.page_number,
        printed_page_label=source.chunk.printed_page_label,
        article_references=list(source.chunk.article_references),
        source_category=str(metadata.get("source_category", "unclassified")),
        legal_force=str(metadata.get("legal_force", "unclassified")),
        authority_scope=str(metadata.get("authority_scope", "unclassified")),
        allowed_classifications=list(metadata.get("allowed_classifications", [])),
        excerpt=_excerpt(source.chunk.content),
        semantic_score=source.semantic_score,
        lexical_score=source.lexical_score,
        fusion_score=source.fusion_score,
    )


def _render_answer(summary: str, findings: list[LegalFinding]) -> str:
    parts = [summary.strip()]
    for finding in findings:
        label = CLASSIFICATION_LABELS[finding.classification]
        references = " ".join(f"[{source_id}]" for source_id in finding.source_ids)
        line = f"- {label}: {finding.statement.strip()} {references}".strip()
        if finding.applicability_note:
            line += f" Aplicabilidad: {finding.applicability_note.strip()}"
        parts.append(line)
    return "\n\n".join(part for part in parts if part)


class LegalRAGService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        *,
        retriever: HybridLegalRetriever | None = None,
        answer_provider: LegalAnswerProvider | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.retriever = retriever or HybridLegalRetriever(db, self.settings)
        self.answer_provider = answer_provider

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_keys: list[str] | None = None,
    ) -> list[LegalCitation]:
        return [
            source_to_citation(source)
            for source in self.retriever.search(
                query,
                top_k=top_k,
                document_keys=document_keys,
            )
        ]

    def answer(
        self,
        query: str,
        *,
        document_keys: list[str] | None = None,
    ) -> LegalQueryResponse:
        trace_id = str(uuid.uuid4())
        started = time.perf_counter()
        indexed_embeddings = self.retriever.indexed_embedding_count()
        manifest = load_manifest(self.settings.legal_rag_corpus_path)
        sources = self.retriever.search(query, document_keys=document_keys)
        if not sources:
            response = LegalQueryResponse(
                answer=(
                    "No encontré evidencia suficiente en el corpus normativo indexado para "
                    "responder con seguridad. Consulte la normativa oficial vigente o solicite "
                    "criterio jurídico institucional."
                ),
                citations=[],
                retrieved_embeddings=0,
                indexed_embeddings=indexed_embeddings,
                trace_id=trace_id,
                model_name=self.settings.legal_rag_model,
                embedding_model=self.settings.legal_rag_embedding_model,
                prompt_version=LEGAL_RAG_PROMPT_VERSION,
                corpus_version=manifest.version,
                insufficient_evidence=True,
                caveats=["La búsqueda no recuperó fragmentos con relevancia mínima."],
            )
            self._record_trace(query, response, started)
            return response
        provider = self.answer_provider or get_legal_answer_provider(self.settings)
        try:
            generated, usage = provider.generate(query, sources)
        except Exception as exc:
            self._record_failure(
                query,
                trace_id,
                indexed_embeddings,
                manifest.version,
                started,
                exc,
            )
            raise
        valid_sources = {source.source_id: source for source in sources}
        findings: list[LegalFinding] = []
        invalid_attribution = False
        cited_ids: list[str] = []
        for generated_finding in generated.findings:
            source_ids = list(dict.fromkeys(generated_finding.source_ids))
            finding_sources = [valid_sources.get(source_id) for source_id in source_ids]
            compatible = bool(finding_sources) and all(
                source is not None
                and generated_finding.classification
                in (source.document.document_metadata or {}).get(
                    "allowed_classifications", []
                )
                for source in finding_sources
            )
            if not compatible:
                invalid_attribution = True
                continue
            findings.append(
                LegalFinding(
                    classification=generated_finding.classification,
                    statement=generated_finding.statement,
                    source_ids=source_ids,
                    applicability_note=generated_finding.applicability_note,
                )
            )
            cited_ids.extend(source_ids)
        cited_ids = list(dict.fromkeys(cited_ids))
        caveats = list(generated.caveats)
        insufficient = generated.insufficient_evidence
        if invalid_attribution:
            insufficient = True
            caveats.append(
                "Se descartó un hallazgo cuya fuente no permitía esa clasificación jurídica."
            )
        attribution_failed = not findings and not generated.insufficient_evidence
        if attribution_failed:
            insufficient = True
            caveats.append("La respuesta no superó la validación automática de atribución.")
            answer = (
                "No fue posible producir una respuesta con atribución verificable. Revise las "
                "fuentes recuperadas o reformule la consulta."
            )
            findings = []
            cited_ids = []
        else:
            answer = _render_answer(generated.summary, findings)
        citations = [source_to_citation(valid_sources[source_id]) for source_id in cited_ids]
        response = LegalQueryResponse(
            answer=answer,
            findings=findings,
            citations=citations,
            retrieved_embeddings=len(sources),
            indexed_embeddings=indexed_embeddings,
            trace_id=trace_id,
            model_name=provider.model_name,
            embedding_model=self.retriever.embedding_provider.model_name,
            prompt_version=LEGAL_RAG_PROMPT_VERSION,
            corpus_version=manifest.version,
            insufficient_evidence=insufficient,
            caveats=caveats,
            usage=usage,
        )
        self._record_trace(query, response, started)
        return response

    def _record_trace(
        self,
        query: str,
        response: LegalQueryResponse,
        started: float,
    ) -> None:
        self.db.add(
            LegalQueryTrace(
                trace_id=response.trace_id,
                query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
                cited_chunk_ids=[citation.chunk_id for citation in response.citations],
                retrieved_embeddings=response.retrieved_embeddings,
                indexed_embeddings=response.indexed_embeddings,
                model_name=response.model_name,
                embedding_model=response.embedding_model,
                prompt_version=response.prompt_version,
                corpus_version=response.corpus_version,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                success=True,
            )
        )
        self.db.add(
            AuditEvent(
                trace_id=response.trace_id,
                actor_role="admin",
                action="legal_rag:query",
                resource_type="legal_corpus",
                details={
                    "retrieved_embeddings": response.retrieved_embeddings,
                    "cited_chunk_ids": [citation.chunk_id for citation in response.citations],
                    "insufficient_evidence": response.insufficient_evidence,
                    "success": True,
                },
            )
        )
        self.db.commit()

    def _record_failure(
        self,
        query: str,
        trace_id: str,
        indexed_embeddings: int,
        corpus_version: str,
        started: float,
        error: Exception,
    ) -> None:
        self.db.add(
            LegalQueryTrace(
                trace_id=trace_id,
                query_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
                cited_chunk_ids=[],
                retrieved_embeddings=0,
                indexed_embeddings=indexed_embeddings,
                model_name=self.settings.legal_rag_model,
                embedding_model=self.settings.legal_rag_embedding_model,
                prompt_version=LEGAL_RAG_PROMPT_VERSION,
                corpus_version=corpus_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                success=False,
                error_type=type(error).__name__,
            )
        )
        self.db.commit()


def corpus_indexer(db: Session, settings: Settings | None = None) -> LegalCorpusIndexer:
    return LegalCorpusIndexer(db, settings or get_settings())

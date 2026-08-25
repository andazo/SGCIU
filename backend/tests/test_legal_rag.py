from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from sqlalchemy import select

from app.config import get_settings
from app.models import LegalChunk, LegalDocument, LegalQueryTrace
from app.rag.corpus import ExtractedPage, LegalCorpusIndexer, chunk_pages
from app.rag.generation import GroundedLegalAnswer, LegalAnswerProvider
from app.rag.retrieval import HybridLegalRetriever
from app.schemas import ModelUsage
from app.services.legal_rag import LegalRAGService
from tests.fakes import LocalEmbeddingDouble


class CitedAnswerDouble(LegalAnswerProvider):
    model_name = "test-legal-answer"

    def generate(self, query, sources):
        return (
            GroundedLegalAnswer(
                answer="El procedimiento debe verificarse con la fuente recuperada [F1].",
                cited_source_ids=["F1"],
            ),
            ModelUsage(input_tokens=25, output_tokens=12),
        )


class InvalidCitationDouble(LegalAnswerProvider):
    model_name = "test-invalid-citation"

    def generate(self, query, sources):
        return (
            GroundedLegalAnswer(
                answer="Afirmación no atribuida [F99].",
                cited_source_ids=["F99"],
            ),
            ModelUsage(),
        )


def _add_legal_chunk(db_session, provider, *, key, title, page, content, priority=1):
    document = LegalDocument(
        document_key=key,
        title=title,
        short_title=title,
        source_filename=f"{key}.pdf",
        source_sha256="a" * 64,
        authority="Autoridad de prueba",
        jurisdiction="Costa Rica",
        document_type="reglamento",
        corpus_version="2026.08.1",
        page_count=page,
        priority=priority,
        status="active",
        document_metadata={},
    )
    db_session.add(document)
    db_session.flush()
    chunk = LegalChunk(
        document_id=document.id,
        chunk_index=0,
        page_number=page,
        article_references=["Artículo 23"],
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        estimated_tokens=100,
        embedding=provider.embed(content),
        embedding_model=provider.model_name,
        corpus_version="2026.08.1",
        chunk_metadata={},
    )
    db_session.add(chunk)
    db_session.commit()
    return chunk


def test_chunking_never_crosses_pdf_pages_and_carries_article_reference():
    pages = [
        ExtractedPage(
            page_number=7,
            printed_page_label="5",
            text=(
                "CAPÍTULO II\nArtículo 23. La autoridad debe documentar la medición del ruido. "
                + " evidencia operativa" * 180
            ),
        ),
        ExtractedPage(
            page_number=8,
            printed_page_label="6",
            text="La actuación continuará con un informe técnico y evidencia suficiente. " * 8,
        ),
    ]

    chunks = chunk_pages(pages, target_tokens=128, overlap_tokens=20)

    assert {chunk.page_number for chunk in chunks} == {7, 8}
    assert all(chunk.estimated_tokens <= 128 for chunk in chunks)
    page_eight = [chunk for chunk in chunks if chunk.page_number == 8]
    assert page_eight
    assert page_eight[0].article_references == ("Artículo 23",)
    assert page_eight[0].printed_page_label == "6"


def test_indexer_persists_complete_document_before_embeddings(
    db_session,
    tmp_path,
    monkeypatch,
):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    pdf_path = pdfs / "reglamento.pdf"
    pdf_path.write_bytes(b"synthetic-pdf-for-unit-test")
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    manifest = {
        "corpus_id": "test-corpus",
        "version": "test-v1",
        "jurisdiction": "Costa Rica",
        "language": "es",
        "description": "Corpus sintético de prueba.",
        "citation_policy": "Página física del PDF.",
        "known_gaps": [],
        "documents": [
            {
                "key": "reglamento-prueba",
                "title": "Reglamento de prueba",
                "short_title": "Reglamento",
                "filename": pdf_path.name,
                "sha256": checksum,
                "authority": "Autoridad de prueba",
                "document_type": "reglamento",
                "priority": 1,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        "app.rag.corpus.extract_pdf_pages",
        lambda _path: [
            ExtractedPage(
                page_number=1,
                printed_page_label=None,
                text="Artículo 1. La autoridad documentará la actuación preventiva municipal.",
            )
        ],
    )
    settings = replace(
        get_settings(),
        legal_rag_corpus_path=tmp_path,
        legal_rag_chunk_tokens=128,
        legal_rag_chunk_overlap_tokens=20,
    )
    indexer = LegalCorpusIndexer(
        db_session,
        settings,
        embedding_provider=LocalEmbeddingDouble(),
    )

    first = indexer.index_all()
    second = indexer.index_all()

    document = db_session.scalar(
        select(LegalDocument).where(LegalDocument.document_key == "reglamento-prueba")
    )
    assert first.documents_indexed == 1
    assert first.embeddings_created == 1
    assert second.documents_skipped == 1
    assert document is not None
    assert document.title == "Reglamento de prueba"
    assert len(document.chunks) == 1


def test_hybrid_retrieval_prioritizes_lexical_and_semantic_legal_evidence(db_session):
    provider = LocalEmbeddingDouble()
    noise = _add_legal_chunk(
        db_session,
        provider,
        key="decreto-ruido",
        title="Reglamento para el control del ruido ambiental",
        page=18,
        content=(
            "El Ministerio de Salud realizará la medición del ruido con sonómetro y "
            "podrá emitir una orden sanitaria."
        ),
    )
    _add_legal_chunk(
        db_session,
        provider,
        key="ley-transito",
        title="Ley de Tránsito",
        page=42,
        content="La licencia de conducir y los requisitos de circulación vehicular.",
        priority=2,
    )
    retriever = HybridLegalRetriever(db_session, embedding_provider=provider)

    results = retriever.search("¿Cómo se mide el ruido con sonómetro?", top_k=2)

    assert results[0].chunk.id == noise.id
    assert results[0].chunk.page_number == 18
    assert results[0].lexical_score > 0


def test_grounded_answer_reports_embedding_counts_and_exact_pdf_page(db_session):
    provider = LocalEmbeddingDouble()
    _add_legal_chunk(
        db_session,
        provider,
        key="reglamento-flores",
        title="Reglamento de la Policía Municipal de Flores",
        page=4,
        content="La Policía Municipal desarrollará funciones preventivas en el cantón.",
    )
    retriever = HybridLegalRetriever(db_session, embedding_provider=provider)
    service = LegalRAGService(
        db_session,
        retriever=retriever,
        answer_provider=CitedAnswerDouble(),
    )

    response = service.answer("¿Qué función preventiva tiene la Policía Municipal?")

    assert response.retrieved_embeddings == 1
    assert response.indexed_embeddings == 1
    assert response.citations[0].pdf_page == 4
    assert response.citations[0].document_key == "reglamento-flores"
    assert response.insufficient_evidence is False
    assert db_session.scalar(
        select(LegalQueryTrace).where(LegalQueryTrace.trace_id == response.trace_id)
    )


def test_answer_fails_closed_when_model_cites_an_unretrieved_source(db_session):
    provider = LocalEmbeddingDouble()
    _add_legal_chunk(
        db_session,
        provider,
        key="reglamento-flores",
        title="Reglamento de la Policía Municipal de Flores",
        page=4,
        content="La Policía Municipal desarrollará funciones preventivas en el cantón.",
    )
    service = LegalRAGService(
        db_session,
        retriever=HybridLegalRetriever(db_session, embedding_provider=provider),
        answer_provider=InvalidCitationDouble(),
    )

    response = service.answer("¿Qué función preventiva tiene la Policía Municipal?")

    assert response.insufficient_evidence is True
    assert response.citations == []
    assert "atribución verificable" in response.answer

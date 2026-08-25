from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.rag.corpus import LegalCorpusIndexer
from app.services.legal_rag import LegalRAGService
from app.tools.registry import ToolDefinition


class LegalToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchLegalSourcesInput(LegalToolInput):
    query: str = Field(min_length=3, max_length=2_000)
    document_keys: list[str] | None = Field(default=None, max_length=20)
    top_k: int = Field(default=8, ge=1, le=12)


class LegalCorpusStatusInput(LegalToolInput):
    pass


def search_legal_sources(
    db: Session,
    arguments: SearchLegalSourcesInput,
) -> dict[str, object]:
    citations = LegalRAGService(db).search(
        arguments.query,
        document_keys=arguments.document_keys,
        top_k=arguments.top_k,
    )
    return {
        "returned": len(citations),
        "sources": [citation.model_dump() for citation in citations],
        "citation_note": (
            "pdf_page es la página física exacta, numerada desde 1, del PDF versionado. "
            "Los scores son señales de ranking y no probabilidades jurídicas."
        ),
    }


def get_legal_corpus_status(
    db: Session,
    _arguments: LegalCorpusStatusInput,
) -> dict[str, object]:
    return LegalCorpusIndexer(db).status().model_dump()


def legal_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="search_legal_sources",
            description=(
                "Recupera fragmentos del corpus normativo costarricense mediante búsqueda "
                "híbrida y devuelve documento, página PDF exacta, artículo y scores. Úsala "
                "para consultas sobre normas, competencias o protocolos policiales."
            ),
            input_model=SearchLegalSourcesInput,
            handler=search_legal_sources,
        ),
        ToolDefinition(
            name="get_legal_corpus_status",
            description=(
                "Informa la versión, documentos y cantidad de embeddings del corpus legal."
            ),
            input_model=LegalCorpusStatusInput,
            handler=get_legal_corpus_status,
        ),
    ]

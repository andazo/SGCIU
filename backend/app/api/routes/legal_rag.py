from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import AdminRole
from app.db import get_db
from app.rag.corpus import LegalCorpusIndexer
from app.schemas import (
    LegalCorpusStatus,
    LegalIndexingRequest,
    LegalIndexingResult,
    LegalQueryRequest,
    LegalQueryResponse,
)
from app.services.legal_rag import LegalRAGService

router = APIRouter(prefix="/legal-rag", tags=["legal-rag"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/corpus", response_model=LegalCorpusStatus)
def legal_corpus_status(db: DbSession, _actor: AdminRole):
    return LegalCorpusIndexer(db).status()


@router.post("/corpus/index", response_model=LegalIndexingResult)
def index_legal_corpus(payload: LegalIndexingRequest, db: DbSession, _actor: AdminRole):
    try:
        return LegalCorpusIndexer(db).index_all(force=payload.force)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503, detail="Servicio de IA temporalmente no disponible."
        ) from exc


@router.post("/query", response_model=LegalQueryResponse)
def query_legal_corpus(payload: LegalQueryRequest, db: DbSession, _actor: AdminRole):
    try:
        return LegalRAGService(db).answer(
            payload.query,
            document_keys=payload.document_keys,
            audience=payload.audience,
            operational_context=payload.operational_context,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503, detail="Servicio de IA temporalmente no disponible."
        ) from exc

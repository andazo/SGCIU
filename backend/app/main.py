import logging
import time
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from .ai_service import run_complaint_intake_chat
from .api.dependencies import AdminRole
from .api.routes.auth import router as auth_router
from .api.routes.incidents import router as incidents_router
from .api.routes.intake import router as intake_router
from .api.routes.internal_intake import router as internal_intake_router
from .api.routes.legal_rag import router as legal_rag_router
from .api.routes.operational import router as operational_router
from .api.routes.reviews import router as reviews_router
from .config import get_settings
from .crud import create_form_submission, list_complaint_submissions, list_form_submissions
from .db import get_db
from .logging_config import configure_logging, correlation_id_context
from .monitoring import (
    DATABASE_READY,
    HTTP_IN_PROGRESS,
    normalized_route,
    prometheus_payload,
    record_http_request,
)
from .schemas import (
    ComplaintIntakeChatRequest,
    ComplaintIntakeChatResponse,
    ComplaintSubmissionCreate,
    ComplaintSubmissionResponse,
    FormSubmissionCreate,
    FormSubmissionResponse,
)
from .services.incidents import IncidentService

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
DbSession = Annotated[Session, Depends(get_db)]

app = FastAPI(title=settings.app_name, version="0.4.0")
app.include_router(intake_router, prefix="/v1")
app.include_router(incidents_router, prefix="/v1")
app.include_router(internal_intake_router, prefix="/v1")
app.include_router(operational_router, prefix="/v1")
app.include_router(reviews_router, prefix="/v1")
app.include_router(legal_rag_router, prefix="/v1")
app.include_router(auth_router, prefix="/v1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    token = correlation_id_context.set(correlation_id)
    started = time.perf_counter()
    status_code = 500
    HTTP_IN_PROGRESS.inc()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        logger.exception(
            "Unhandled request error",
            extra={"method": request.method, "path": request.url.path},
        )
        response = JSONResponse(status_code=500, content={"detail": "Internal error"})
    finally:
        duration_seconds = time.perf_counter() - started
        elapsed_ms = round(duration_seconds * 1000, 2)
        route = normalized_route(request.scope)
        record_http_request(
            method=request.method,
            route=route,
            status_code=status_code,
            duration_seconds=duration_seconds,
        )
        HTTP_IN_PROGRESS.dec()
        logger.info(
            "Request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "route": route,
                "status_code": status_code,
                "latency_ms": elapsed_ms,
            },
        )
        correlation_id_context.reset(token)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def readiness(db: DbSession):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        DATABASE_READY.set(0)
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    DATABASE_READY.set(1)
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    payload, content_type = prometheus_payload()
    return Response(content=payload, media_type=content_type)


@app.post("/submissions", response_model=FormSubmissionResponse)
def create_submission(payload: FormSubmissionCreate, db: DbSession):
    return create_form_submission(db, payload)


@app.get("/submissions", response_model=list[FormSubmissionResponse])
def get_submissions(db: DbSession, _actor: AdminRole):
    return list_form_submissions(db)


@app.post("/ai/intake/chat", response_model=ComplaintIntakeChatResponse)
def complaint_intake_chat(payload: ComplaintIntakeChatRequest):
    return run_complaint_intake_chat(payload)


@app.post("/complaints", response_model=ComplaintSubmissionResponse)
def create_complaint(payload: ComplaintSubmissionCreate, db: DbSession):
    if payload.police_input:
        raise HTTPException(
            status_code=403,
            detail="Los registros de personal deben utilizar el flujo interno administrativo.",
        )
    # Keep the legacy route compatible, but send it through the same domain service
    # as persistent intake so embeddings and administrative assessment are not skipped.
    return IncidentService(db).create(payload)


@app.get("/complaints", response_model=list[ComplaintSubmissionResponse])
def get_complaints(db: DbSession, _actor: AdminRole):
    return list_complaint_submissions(db)

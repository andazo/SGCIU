import logging
import time
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .ai_service import run_complaint_intake_chat
from .api.routes.incidents import router as incidents_router
from .api.routes.intake import router as intake_router
from .config import get_settings
from .crud import (
    create_complaint_submission,
    create_form_submission,
    list_complaint_submissions,
    list_form_submissions,
)
from .db import get_db
from .logging_config import configure_logging, correlation_id_context
from .schemas import (
    ComplaintIntakeChatRequest,
    ComplaintIntakeChatResponse,
    ComplaintSubmissionCreate,
    ComplaintSubmissionResponse,
    FormSubmissionCreate,
    FormSubmissionResponse,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
DbSession = Annotated[Session, Depends(get_db)]

app = FastAPI(title=settings.app_name, version="0.2.0")
app.include_router(intake_router, prefix="/v1")
app.include_router(incidents_router, prefix="/v1")

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
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled request error",
            extra={"method": request.method, "path": request.url.path},
        )
        response = JSONResponse(status_code=500, content={"detail": "Internal error"})
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "Request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
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
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post("/submissions", response_model=FormSubmissionResponse)
def create_submission(payload: FormSubmissionCreate, db: DbSession):
    return create_form_submission(db, payload)


@app.get("/submissions", response_model=list[FormSubmissionResponse])
def get_submissions(db: DbSession):
    return list_form_submissions(db)


@app.post("/ai/intake/chat", response_model=ComplaintIntakeChatResponse)
def complaint_intake_chat(payload: ComplaintIntakeChatRequest):
    return run_complaint_intake_chat(payload)


@app.post("/complaints", response_model=ComplaintSubmissionResponse)
def create_complaint(payload: ComplaintSubmissionCreate, db: DbSession):
    return create_complaint_submission(db, payload)


@app.get("/complaints", response_model=list[ComplaintSubmissionResponse])
def get_complaints(db: DbSession):
    return list_complaint_submissions(db)

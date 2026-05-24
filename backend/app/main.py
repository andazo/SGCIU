from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .ai_service import run_complaint_intake_chat
from .db import Base, engine, get_db
from .schemas import (
    ComplaintIntakeChatRequest,
    ComplaintIntakeChatResponse,
    ComplaintSubmissionCreate,
    ComplaintSubmissionResponse,
    FormSubmissionCreate,
    FormSubmissionResponse,
)
from .crud import (
    create_complaint_submission,
    create_form_submission,
    list_complaint_submissions,
    list_form_submissions,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/submissions", response_model=FormSubmissionResponse)
def create_submission(payload: FormSubmissionCreate, db: Session = Depends(get_db)):
    return create_form_submission(db, payload)

@app.get("/submissions", response_model=list[FormSubmissionResponse])
def get_submissions(db: Session = Depends(get_db)):
    return list_form_submissions(db)


@app.post("/ai/intake/chat", response_model=ComplaintIntakeChatResponse)
def complaint_intake_chat(payload: ComplaintIntakeChatRequest):
    return run_complaint_intake_chat(payload)


@app.post("/complaints", response_model=ComplaintSubmissionResponse)
def create_complaint(payload: ComplaintSubmissionCreate, db: Session = Depends(get_db)):
    return create_complaint_submission(db, payload)


@app.get("/complaints", response_model=list[ComplaintSubmissionResponse])
def get_complaints(db: Session = Depends(get_db)):
    return list_complaint_submissions(db)

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from .schemas import FormSubmissionCreate, FormSubmissionResponse
from .crud import create_form_submission, list_form_submissions

Base.metadata.create_all(bind=engine)

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
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

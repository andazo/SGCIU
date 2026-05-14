from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class FormSubmissionCreate(BaseModel):
    name: str
    email: EmailStr
    message: Optional[str] = None

class FormSubmissionResponse(BaseModel):
    id: int
    name: str
    email: str
    message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

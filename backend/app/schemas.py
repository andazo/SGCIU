from pydantic import BaseModel, EmailStr, Field
from pydantic import ConfigDict, field_validator, model_validator
from typing import Literal, Optional
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


RelacionIncidente = Literal["victima", "testigo", "vecino", "comerciante", "otro"]
CategoriaPreliminar = Literal[
    "ruido",
    "vehiculo_sospechoso",
    "venta_drogas",
    "violencia",
    "robo",
    "vandalismo",
    "persona_sospechosa",
    "emergencia",
    "disturbio_publico",
    "basura_o_contaminacion",
    "alumbrado_publico",
    "obstruccion_via_publica",
    "animal_peligroso",
    "consumo_alcohol_drogas",
    "acoso_o_amenaza",
    "problema_transito",
    "otro",
]
Distrito = Literal["San Joaquin", "Barrantes", "Llorente"]
TipoLugar = Literal["establecimiento", "casa", "parque", "escuela", "otro"]


class ComplaintExtractedData(BaseModel):
    descripcion_detallada: Optional[str] = None
    relacion_incidente: Optional[RelacionIncidente] = None
    categoria_preliminar: Optional[CategoriaPreliminar] = None
    distrito: Optional[Distrito] = None
    direccion_exacta: Optional[str] = None
    tipo_lugar: Optional[TipoLugar] = None
    fecha_hora_aproximada: Optional[str] = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str):
        if not value.strip():
            raise ValueError("El mensaje no puede estar vacío.")
        return value.strip()


class ComplaintIntakeChatRequest(BaseModel):
    messages: list[ChatMessage]
    current_extracted_data: Optional[ComplaintExtractedData] = None


class ComplaintIntakeChatResponse(BaseModel):
    assistant_message: str
    is_complete: bool
    missing_fields: list[str]
    extracted_data: ComplaintExtractedData
    summary_text: Optional[str] = None
    summary_bullets: list[str] = Field(default_factory=list)


class ComplaintSubmissionCreate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    ai_extracted_data: ComplaintExtractedData
    ai_summary_text: Optional[str] = None
    truth_confirmation: bool
    data_usage_consent: bool

    @field_validator("name", "phone", "ai_summary_text", mode="before")
    @classmethod
    def empty_strings_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_required_complaint_fields(self):
        if not self.truth_confirmation:
            raise ValueError("Debe confirmar la veracidad de la información.")
        if not self.data_usage_consent:
            raise ValueError("Debe aceptar el uso institucional de los datos.")
        if not self.ai_extracted_data.descripcion_detallada:
            raise ValueError("La descripción detallada de la denuncia es obligatoria.")
        return self


class ComplaintSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    ai_extracted_data: ComplaintExtractedData
    ai_summary_text: Optional[str]
    truth_confirmation: bool
    data_usage_consent: bool
    created_at: datetime

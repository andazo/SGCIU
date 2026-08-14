from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

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
Urgencia = Literal["baja", "media", "alta", "inmediata"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FormSubmissionCreate(BaseModel):
    name: str
    email: EmailStr
    message: str | None = None


class FormSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    message: str | None
    created_at: datetime


class EntityEvidence(StrictModel):
    entity_type: str
    value: str
    source_text: str


class IncidentEntities(StrictModel):
    people: list[str] = Field(default_factory=list)
    vehicles: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    establishments: list[str] = Field(default_factory=list)
    landmarks: list[str] = Field(default_factory=list)
    temporal_references: list[str] = Field(default_factory=list)
    evidence: list[EntityEvidence] = Field(default_factory=list)


class FieldConfidence(StrictModel):
    descripcion_detallada: float | None = None
    relacion_incidente: float | None = None
    categoria_preliminar: float | None = None
    distrito: float | None = None
    direccion_exacta: float | None = None
    tipo_lugar: float | None = None
    fecha_hora_aproximada: float | None = None

    @model_validator(mode="after")
    def scores_must_be_normalized(self):
        scores = self.model_dump(exclude_none=True)
        if any(score < 0 or score > 1 for score in scores.values()):
            raise ValueError("Los valores de confianza deben estar entre 0 y 1.")
        return self


class ComplaintExtractedData(StrictModel):
    descripcion_detallada: str | None = None
    relacion_incidente: RelacionIncidente | None = None
    categoria_preliminar: CategoriaPreliminar | None = None
    distrito: Distrito | None = None
    direccion_exacta: str | None = None
    tipo_lugar: TipoLugar | None = None
    fecha_hora_aproximada: str | None = None
    entities: IncidentEntities = Field(default_factory=IncidentEntities)
    urgency: Urgencia = "media"
    confidence_by_field: FieldConfidence = Field(default_factory=FieldConfidence)


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str):
        if not value.strip():
            raise ValueError("El mensaje no puede estar vacío.")
        return value.strip()


class ComplaintIntakeChatRequest(StrictModel):
    messages: list[ChatMessage]
    current_extracted_data: ComplaintExtractedData | None = None


class ComplaintIntakeChatResponse(StrictModel):
    assistant_message: str
    is_complete: bool
    missing_fields: list[str]
    extracted_data: ComplaintExtractedData
    summary_text: str | None = None
    summary_bullets: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    review_reason: str | None = None
    emergency_guidance: bool = False
    model_name: str | None = None
    prompt_version: str = "intake-v2"


class IntakeSessionCreateResponse(StrictModel):
    session_id: str
    assistant_message: str
    prompt_version: str


class IntakeMessageRequest(StrictModel):
    content: str = Field(min_length=1, max_length=8_000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str):
        return value.strip()


class IntakeSessionResponse(StrictModel):
    session_id: str
    messages: list[ChatMessage]
    is_complete: bool
    missing_fields: list[str]
    extracted_data: ComplaintExtractedData
    summary_text: str | None
    requires_human_review: bool
    review_reason: str | None
    model_name: str | None
    prompt_version: str


class ComplaintSubmissionCreate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    ai_extracted_data: ComplaintExtractedData
    ai_summary_text: str | None = None
    analysis_metadata: dict[str, object] = Field(default_factory=dict)
    requires_human_review: bool = False
    review_reason: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    truth_confirmation: bool
    data_usage_consent: bool

    @field_validator("name", "phone", "ai_summary_text", "review_reason", mode="before")
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


class IntakeSubmissionRequest(StrictModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    truth_confirmation: bool
    data_usage_consent: bool


class ComplaintSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    email: str | None
    phone: str | None
    ai_extracted_data: ComplaintExtractedData
    ai_summary_text: str | None
    analysis_metadata: dict[str, object] = Field(default_factory=dict)
    status: str = "submitted"
    requires_human_review: bool = False
    review_reason: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    truth_confirmation: bool
    data_usage_consent: bool
    created_at: datetime
    updated_at: datetime | None = None


class IncidentListResponse(StrictModel):
    items: list[ComplaintSubmissionResponse]
    total: int
    limit: int
    offset: int


class HumanReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    reason: str
    status: str
    resolution_notes: str | None
    created_at: datetime
    resolved_at: datetime | None


class RelatedIncident(StrictModel):
    incident_id: int
    category: str | None
    district: str | None
    address: str | None
    similarity_score: float
    semantic_score: float
    match_reasons: list[str]


class RelatedIncidentList(StrictModel):
    source_incident_id: int
    items: list[RelatedIncident]


class ClusterMemberResponse(StrictModel):
    incident_id: int
    similarity_score: float
    match_reason: str


class IncidentClusterResponse(StrictModel):
    id: int
    label: str
    status: str
    explanation: str | None
    members: list[ClusterMemberResponse]


class OperationalQueryRequest(StrictModel):
    query: str = Field(min_length=3, max_length=2_000)


class ToolExecutionTrace(StrictModel):
    step: int
    tool_name: str
    arguments: dict[str, object]
    success: bool
    result_count: int | None = None
    latency_ms: float
    error_type: str | None = None


class ModelUsage(StrictModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class OperationalQueryResponse(StrictModel):
    answer: str
    incident_citations: list[int]
    trace_id: str
    steps: list[ToolExecutionTrace]
    model_name: str
    prompt_version: str
    requires_human_review: bool = False
    usage: ModelUsage = Field(default_factory=ModelUsage)


class ResolveReviewRequest(StrictModel):
    notes: str = Field(min_length=3, max_length=2_000)


class AssistantFeedbackRequest(StrictModel):
    trace_id: str
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


class AssistantFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trace_id: str
    actor_role: str
    rating: int
    comment: str | None
    created_at: datetime

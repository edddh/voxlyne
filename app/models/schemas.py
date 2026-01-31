"""
Ascolta - Pydantic Schemas
Data models for API requests/responses and database entities
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ===========================================
# Enums
# ===========================================

class CallStatus(str, Enum):
    """Call lifecycle status."""
    PENDING_CONSENT = "pending_consent"
    CONSENTED = "consented"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PROCESSING = "processing"
    PROCESSED = "processed"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class TranscriptRole(str, Enum):
    """Message sender role."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ProjectType(str, Enum):
    """Project use case type."""
    RECRUITING = "recruiting"
    LEAD_GEN = "lead_gen"
    SUPPORT = "support"
    SURVEY = "survey"
    OTHER = "other"


# ===========================================
# Call Schemas
# ===========================================

class CallBase(BaseModel):
    """Base call model."""
    phone_number: Optional[str] = None
    status: CallStatus = CallStatus.PENDING_CONSENT
    project_id: Optional[UUID] = None  # M2: Link to project


class CallCreate(CallBase):
    """Schema for creating a new call."""
    openai_session_id: Optional[str] = None


class CallUpdate(BaseModel):
    """Schema for updating a call."""
    status: Optional[CallStatus] = None
    consent_given: Optional[bool] = None
    consent_timestamp: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    openai_session_id: Optional[str] = None


class Call(CallBase):
    """Complete call model with all fields."""
    id: UUID
    project_id: Optional[UUID] = None  # M2: Foreign key to projects
    consent_given: bool = False
    consent_timestamp: Optional[datetime] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    openai_session_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CallWithTranscripts(Call):
    """Call with its transcripts."""
    transcripts: List["Transcript"] = []


# ===========================================
# Transcript Schemas
# ===========================================

class TranscriptBase(BaseModel):
    """Base transcript model."""
    role: TranscriptRole
    content: str


class TranscriptCreate(TranscriptBase):
    """Schema for creating a transcript entry."""
    call_id: UUID


class Transcript(TranscriptBase):
    """Complete transcript model."""
    id: int
    call_id: UUID
    timestamp: datetime

    class Config:
        from_attributes = True


# ===========================================
# API Response Schemas
# ===========================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    database: bool = True
    version: str = "1.0.0"
    environment: str = "development"


class CallListResponse(BaseModel):
    """Paginated call list response."""
    calls: List[Call]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None


# ===========================================
# Webhook Schemas (OpenAI SIP)
# ===========================================

class OpenAICallEvent(BaseModel):
    """
    OpenAI SIP call event webhook payload.
    Note: Exact schema depends on OpenAI documentation.
    """
    event_type: str
    call_id: Optional[str] = None
    session_id: Optional[str] = None
    caller_number: Optional[str] = None
    timestamp: Optional[datetime] = None
    # Additional fields as per OpenAI spec
    data: Optional[dict] = None


class DTMFEvent(BaseModel):
    """DTMF tone event."""
    digit: str
    call_id: UUID
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ===========================================
# GDPR Schemas
# ===========================================

class GDPRDeleteRequest(BaseModel):
    """Request to delete all data for a call."""
    call_id: UUID
    reason: str = "user_request"  # user_request, dtmf_cancel, etc.


class GDPRDeleteResponse(BaseModel):
    """Response after GDPR deletion."""
    success: bool
    message: str
    records_deleted: int = 0


# ===========================================
# Project Schemas (M2)
# ===========================================

class ProjectBase(BaseModel):
    """Base project model."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    type: ProjectType
    description: Optional[str] = None
    is_active: bool = True


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""
    prompt_a: str = Field(..., min_length=100)
    prompt_b: str = Field(..., min_length=100)
    consent_message: Optional[str] = None
    voice_name: str = "alloy"
    language: str = "it"
    output_config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "pdf": {"enabled": True, "template": "default"},
            "email": {"enabled": False, "to": []},
            "webhook": {"enabled": False, "url": None}
        }
    )
    sip_number: Optional[str] = None
    openai_project_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    prompt_a: Optional[str] = Field(None, min_length=100)
    prompt_b: Optional[str] = Field(None, min_length=100)
    consent_message: Optional[str] = None
    voice_name: Optional[str] = None
    language: Optional[str] = None
    output_config: Optional[Dict[str, Any]] = None
    sip_number: Optional[str] = None
    openai_project_id: Optional[str] = None


class Project(ProjectBase):
    """Complete project model."""
    id: UUID
    prompt_a: str
    prompt_b: str
    consent_message: Optional[str] = None
    voice_name: str
    language: str
    output_config: Dict[str, Any]
    sip_number: Optional[str] = None
    openai_project_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# Record Schemas (M2)
# ===========================================

class RecordBase(BaseModel):
    """Base record model."""
    json_data: Dict[str, Any]


class RecordCreate(RecordBase):
    """Schema for creating a record."""
    call_id: UUID


class RecordUpdate(BaseModel):
    """Schema for updating a record."""
    json_data: Optional[Dict[str, Any]] = None
    pdf_key: Optional[str] = None
    pdf_generated_at: Optional[datetime] = None
    email_sent: Optional[bool] = None
    email_sent_at: Optional[datetime] = None
    email_to: Optional[str] = None


class Record(RecordBase):
    """Complete record model."""
    id: int
    call_id: UUID
    pdf_key: Optional[str] = None
    pdf_generated_at: Optional[datetime] = None
    email_sent: bool = False
    email_sent_at: Optional[datetime] = None
    email_to: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RecordWithCall(Record):
    """Record with associated call data."""
    call: Optional[Call] = None


# ===========================================
# Setting Schemas (M2)
# ===========================================

class SettingBase(BaseModel):
    """Base setting model."""
    key: str = Field(..., min_length=1, max_length=255)
    value: str


class SettingCreate(SettingBase):
    """Schema for creating a setting."""
    description: Optional[str] = None


class SettingUpdate(BaseModel):
    """Schema for updating a setting."""
    value: str


class Setting(SettingBase):
    """Complete setting model."""
    description: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# Metric Schemas (M2)
# ===========================================

class MetricBase(BaseModel):
    """Base metric model."""
    date: datetime
    total_calls: int = 0
    consented_calls: int = 0
    declined_calls: int = 0
    cancelled_calls: int = 0
    completed_calls: int = 0


class Metric(MetricBase):
    """Complete metric model."""
    id: int
    avg_duration_seconds: Optional[float] = None
    avg_consent_time_seconds: Optional[float] = None
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================
# Extended Call Schemas (M2)
# ===========================================

class CallWithProject(Call):
    """Call with project information."""
    project: Optional[Project] = None


class CallWithRecord(Call):
    """Call with record (JSON + PDF)."""
    record: Optional[Record] = None


class CallComplete(Call):
    """Call with all related data."""
    project: Optional[Project] = None
    record: Optional[Record] = None
    transcripts: List[Transcript] = []


# Update forward references
CallWithTranscripts.model_rebuild()
CallWithProject.model_rebuild()
CallWithRecord.model_rebuild()
CallComplete.model_rebuild()
RecordWithCall.model_rebuild()

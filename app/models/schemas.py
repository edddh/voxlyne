"""
Ascolta - Pydantic Schemas
Data models for API requests/responses and database entities
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
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


# ===========================================
# Call Schemas
# ===========================================

class CallBase(BaseModel):
    """Base call model."""
    phone_number: Optional[str] = None
    status: CallStatus = CallStatus.PENDING_CONSENT


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


# Update forward references
CallWithTranscripts.model_rebuild()

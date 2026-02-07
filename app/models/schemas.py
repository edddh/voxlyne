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


class VoiceEngineType(str, Enum):
    """Supported voice engine providers."""
    OPENAI_REALTIME = "openai_realtime"
    VAPI = "vapi"


class CallDirection(str, Enum):
    """Call direction."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BOTH = "both"


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
    # M5: Voice engine & direction tracking
    voice_engine: Optional[str] = None
    direction: str = "inbound"
    vapi_call_id: Optional[str] = None
    twilio_call_sid: Optional[str] = None


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
    # M5: Voice engine & direction tracking
    voice_engine: Optional[str] = None
    direction: str = "inbound"
    vapi_call_id: Optional[str] = None
    twilio_call_sid: Optional[str] = None
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
    type: ProjectType = ProjectType.RECRUITING
    description: Optional[str] = None
    is_active: bool = True


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""
    prompt_a: str = Field(
        default=(
            "Sei un assistente AI che conduce una breve intervista professionale. "
            "Inizia chiedendo il consenso al trattamento dati, poi fai domande chiare "
            "sull'esperienza, competenze, motivazioni e disponibilita. Mantieni un tono "
            "cordiale, non interrompere l'utente e chiudi con un riepilogo sintetico."
        ),
        min_length=100,
    )
    prompt_b: str = Field(
        default=(
            "Analizza la trascrizione e restituisci solo JSON valido con: nome candidato, "
            "telefono, email, riepilogo esperienza, competenze tecniche, soft skills, "
            "disponibilita, motivazioni, criticita e punteggio complessivo 1-10. "
            "Non inventare dati e usa null o [] quando le informazioni non sono presenti."
        ),
        min_length=100,
    )
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
    # M5: Voice engine configuration
    voice_engine: VoiceEngineType = VoiceEngineType.OPENAI_REALTIME
    call_direction: CallDirection = CallDirection.INBOUND
    vapi_assistant_id: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None


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
    # M5: Voice engine configuration
    voice_engine: Optional[VoiceEngineType] = None
    call_direction: Optional[CallDirection] = None
    vapi_assistant_id: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None


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
    # M5: Voice engine configuration
    voice_engine: str = "openai_realtime"
    call_direction: str = "inbound"
    vapi_assistant_id: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
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


# ===========================================
# CRM Schemas (M3)
# ===========================================

class CRMSyncStatus(str, Enum):
    """CRM sync status."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class CRMProvider(str, Enum):
    """Supported CRM providers."""
    HUBSPOT = "hubspot"
    SALESFORCE = "salesforce"
    GENERIC_WEBHOOK = "generic_webhook"


class CRMSyncLogBase(BaseModel):
    """Base CRM sync log model."""
    provider: str
    operation: str
    status: CRMSyncStatus = CRMSyncStatus.PENDING


class CRMSyncLog(CRMSyncLogBase):
    """Complete CRM sync log entry."""
    id: int
    call_id: UUID
    record_id: Optional[int] = None
    external_id: Optional[str] = None
    response_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    next_retry_at: Optional[datetime] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CRMStatusResponse(BaseModel):
    """Response for CRM status endpoint."""
    call_id: UUID
    synced: bool
    provider: Optional[str] = None
    external_id: Optional[str] = None
    synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    sync_log: List[CRMSyncLog] = []


class CRMTestConnectionRequest(BaseModel):
    """Request to test CRM connection."""
    provider: CRMProvider
    credentials: Dict[str, str] = Field(
        default_factory=dict,
        description="Provider credentials (api_key, access_token, etc.)"
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional provider config (webhook URL, etc.)"
    )


class CRMTestConnectionResponse(BaseModel):
    """Response from connection test."""
    success: bool
    message: str
    provider: str
    details: Optional[Dict[str, Any]] = None


class CRMRetryRequest(BaseModel):
    """Request to retry CRM sync."""
    call_id: UUID


class CRMRetryResponse(BaseModel):
    """Response from retry request."""
    success: bool
    message: str
    call_id: UUID


class CRMStatsResponse(BaseModel):
    """CRM sync statistics."""
    total_syncs: int = 0
    successful: int = 0
    failed: int = 0
    pending: int = 0
    by_provider: Dict[str, int] = Field(default_factory=dict)
    recent_failures: List[CRMSyncLog] = []


class RecordWithCRM(Record):
    """Record with CRM sync status."""
    crm_synced: bool = False
    crm_synced_at: Optional[datetime] = None
    crm_external_id: Optional[str] = None
    crm_provider: Optional[str] = None
    crm_error: Optional[str] = None


# ===========================================
# Calendar Schemas (M3.5)
# ===========================================

class CalendarProvider(str, Enum):
    """Supported calendar providers."""
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class CalendarEventStatus(str, Enum):
    """Calendar event status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class CalendarSlotResponse(BaseModel):
    """Available calendar slot."""
    start: datetime
    end: datetime
    duration_minutes: int = 30
    display_text: str = ""  # Human-readable in Italian


class CalendarSlotsResponse(BaseModel):
    """Response with available slots."""
    call_id: UUID
    slots: List[CalendarSlotResponse] = []
    provider: Optional[str] = None
    calendar_enabled: bool = False


class ScheduleAppointmentRequest(BaseModel):
    """Request to schedule an appointment."""
    call_id: UUID
    slot_start: datetime
    slot_end: datetime
    hr_email: Optional[str] = None


class ScheduleAppointmentResponse(BaseModel):
    """Response from scheduling appointment."""
    success: bool
    message: str
    event_id: Optional[str] = None
    event_link: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class CalendarEventResponse(BaseModel):
    """Calendar event details."""
    id: int
    call_id: UUID
    provider: str
    external_event_id: Optional[str] = None
    event_link: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int = 30
    status: CalendarEventStatus = CalendarEventStatus.PENDING
    attendee_emails: List[str] = []
    invite_sent: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class CalendarTestConnectionRequest(BaseModel):
    """Request to test calendar connection."""
    provider: CalendarProvider
    access_token: str
    refresh_token: Optional[str] = None


class CalendarTestConnectionResponse(BaseModel):
    """Response from connection test."""
    success: bool
    message: str
    provider: str


class RecordWithCalendar(Record):
    """Record with calendar appointment info."""
    appointment_scheduled: bool = False
    appointment_datetime: Optional[datetime] = None
    calendar_event: Optional[CalendarEventResponse] = None


# ===========================================
# Auth Schemas (M4)
# ===========================================

class UserRole(str, Enum):
    """User role for RBAC."""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    CREATOR = "creator"
    POWER_USER = "power_user"
    USER = "user"


class LoginRequest(BaseModel):
    """Login request."""
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginResponse(BaseModel):
    """Login response with tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserResponse"


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    """New access token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserBase(BaseModel):
    """Base user model."""
    email: str = Field(..., min_length=3, max_length=255)
    full_name: Optional[str] = Field(None, max_length=255)
    role: UserRole = UserRole.USER


class UserCreate(UserBase):
    """Schema for creating a user."""
    password: str = Field(..., min_length=8)
    tenant_id: Optional[UUID] = None


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    email: Optional[str] = Field(None, min_length=3, max_length=255)
    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


class UserResponse(BaseModel):
    """User response model."""
    id: UUID
    tenant_id: Optional[UUID] = None
    email: str
    full_name: Optional[str] = None
    role: UserRole
    is_active: bool = True
    email_verified: bool = False
    avatar_url: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    tenant_name: Optional[str] = None
    tenant_slug: Optional[str] = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Paginated user list response."""
    users: List[UserResponse]
    total: int
    page: int
    page_size: int


class PasswordResetRequest(BaseModel):
    """Password reset request."""
    new_password: str = Field(..., min_length=8)


# ===========================================
# Tenant Schemas (M4)
# ===========================================

class TenantBase(BaseModel):
    """Base tenant model."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern="^[a-z0-9-]+$")


class TenantCreate(TenantBase):
    """Schema for creating a tenant."""
    settings: Dict[str, Any] = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    """Schema for updating a tenant."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


class TenantResponse(TenantBase):
    """Tenant response model."""
    id: UUID
    is_active: bool = True
    settings: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    project_count: int = 0

    class Config:
        from_attributes = True


class TenantListResponse(BaseModel):
    """Paginated tenant list response."""
    tenants: List[TenantResponse]
    total: int
    page: int
    page_size: int


# ===========================================
# Prompt Version Schemas (M4)
# ===========================================

class PromptType(str, Enum):
    """Prompt type (A or B)."""
    A = "A"
    B = "B"


class PromptVersionBase(BaseModel):
    """Base prompt version model."""
    prompt_type: PromptType
    content: str = Field(..., min_length=10)


class PromptVersionCreate(PromptVersionBase):
    """Schema for creating a prompt version."""
    pass


class PromptVersionResponse(PromptVersionBase):
    """Prompt version response model."""
    id: UUID
    project_id: UUID
    version: int
    is_active: bool = False
    created_by: Optional[UUID] = None
    created_at: datetime
    creator_name: Optional[str] = None

    class Config:
        from_attributes = True


class PromptVersionListResponse(BaseModel):
    """List of prompt versions."""
    versions: List[PromptVersionResponse]
    active_version: Optional[int] = None
    total: int


class PromptDiffResponse(BaseModel):
    """Diff between two prompt versions."""
    version_a: PromptVersionResponse
    version_b: PromptVersionResponse
    diff: List[str]  # Unified diff lines
    additions: int
    deletions: int


class PromptActivateResponse(BaseModel):
    """Response from activating a prompt version."""
    success: bool
    message: str
    version_id: UUID
    version: int
    prompt_type: PromptType


# ===========================================
# Analytics Schemas (M4)
# ===========================================

class DashboardStats(BaseModel):
    """Dashboard statistics."""
    total_calls_today: int = 0
    total_calls_week: int = 0
    total_calls_month: int = 0
    completed_calls_today: int = 0
    conversion_rate: float = 0.0  # Percentage of completed calls
    avg_duration_seconds: float = 0.0
    active_projects: int = 0
    crm_synced_count: int = 0
    appointments_scheduled_count: int = 0


class CallTrendPoint(BaseModel):
    """Single point in call trend data."""
    date: datetime
    total: int = 0
    completed: int = 0
    cancelled: int = 0


class CallTrendResponse(BaseModel):
    """Call trend over time."""
    points: List[CallTrendPoint]
    period: str  # "day", "week", "month"
    total_calls: int = 0


class ProjectStatsResponse(BaseModel):
    """Statistics for a project."""
    project_id: UUID
    project_name: str
    total_calls: int = 0
    completed_calls: int = 0
    conversion_rate: float = 0.0
    avg_duration_seconds: float = 0.0


# ===========================================
# Outbound Call Schemas (M5)
# ===========================================

class OutboundCallRequest(BaseModel):
    """Request to initiate an outbound call."""
    phone_number: str = Field(..., description="Phone number to call (E.164 format)")
    project_id: UUID = Field(..., description="Project to use for the call")
    metadata: Optional[Dict[str, Any]] = None


class OutboundCallResponse(BaseModel):
    """Response from initiating an outbound call."""
    success: bool
    call_id: Optional[UUID] = None
    provider_call_id: Optional[str] = None
    message: str = ""
    voice_engine: Optional[str] = None


class OutboundCallStatusResponse(BaseModel):
    """Outbound call status."""
    call_id: UUID
    status: CallStatus
    direction: str = "outbound"
    voice_engine: Optional[str] = None
    vapi_call_id: Optional[str] = None
    phone_number: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None


# Update forward references
CallWithTranscripts.model_rebuild()
CallWithProject.model_rebuild()
CallWithRecord.model_rebuild()
CallComplete.model_rebuild()
RecordWithCall.model_rebuild()
LoginResponse.model_rebuild()

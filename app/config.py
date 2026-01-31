"""
Ascolta - Configuration
Pydantic Settings for environment-based configuration
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ===========================================
    # OpenAI Configuration
    # ===========================================
    openai_api_key: str = Field(..., description="OpenAI API Key")
    openai_project_id: str = Field(..., description="OpenAI Project ID for SIP routing")

    # OpenAI Realtime API settings
    openai_realtime_model: str = Field(
        default="gpt-4o-realtime-preview",
        description="OpenAI Realtime model to use"
    )
    openai_realtime_voice: str = Field(
        default="alloy",
        description="Voice for OpenAI TTS (alloy, echo, fable, onyx, nova, shimmer)"
    )

    # ===========================================
    # Database Configuration
    # ===========================================
    database_url: str = Field(
        default="postgresql://ascolta:ascolta_password@localhost:5432/ascolta",
        description="PostgreSQL connection URL"
    )

    # ===========================================
    # Security
    # ===========================================
    secret_key: str = Field(..., description="Secret key for session signing")
    admin_username: str = Field(default="admin", description="Admin username")
    admin_password: str = Field(..., description="Admin password")

    # ===========================================
    # Application Settings
    # ===========================================
    app_env: str = Field(default="development", description="Environment (development/production)")
    log_level: str = Field(default="INFO", description="Logging level")
    webhook_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for webhooks (ngrok or production domain)"
    )

    # ===========================================
    # Voice AI Settings
    # ===========================================
    silence_timeout_seconds: int = Field(
        default=5,
        description="Seconds of silence before prompting user"
    )
    max_call_duration_seconds: int = Field(
        default=900,  # 15 minutes
        description="Maximum call duration before auto-hangup"
    )
    dtmf_cancel_key: str = Field(
        default="9",
        description="DTMF key to trigger immediate cancellation"
    )

    # ===========================================
    # GDPR Settings
    # ===========================================
    gdpr_consent_timeout_seconds: int = Field(
        default=30,
        description="Seconds to wait for consent before hanging up"
    )

    # ===========================================
    # Future Milestones (M2+)
    # ===========================================
    # MinIO/S3
    s3_endpoint: Optional[str] = Field(default=None, description="S3/MinIO endpoint URL")
    s3_access_key: Optional[str] = Field(default=None, description="S3 access key")
    s3_secret_key: Optional[str] = Field(default=None, description="S3 secret key")
    s3_bucket: str = Field(default="ascolta-talento", description="S3 bucket name")
    s3_region: str = Field(default="us-east-1", description="S3 region")

    # Email
    smtp_host: Optional[str] = Field(default=None, description="SMTP host")
    smtp_port: int = Field(default=587, description="SMTP port")
    smtp_user: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password")
    email_from: Optional[str] = Field(default=None, description="From email address")
    email_to_default: Optional[str] = Field(default=None, description="Default recipient")
    email_enabled: bool = Field(default=False, description="Enable email sending")

    # ===========================================
    # Validators
    # ===========================================
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        valid_envs = ["development", "staging", "production"]
        v = v.lower()
        if v not in valid_envs:
            raise ValueError(f"app_env must be one of {valid_envs}")
        return v

    # ===========================================
    # Computed Properties
    # ===========================================
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def openai_sip_uri(self) -> str:
        """Get the OpenAI SIP URI for Zadarma forwarding."""
        return f"sip:{self.openai_project_id}@sip.api.openai.com;transport=tls"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

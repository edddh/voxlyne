"""
Ascolta - CRM Base Classes

Abstract base class and types for CRM integrations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CRMProvider(str, Enum):
    """Supported CRM providers."""
    HUBSPOT = "hubspot"
    SALESFORCE = "salesforce"
    GENERIC_WEBHOOK = "generic_webhook"


class CRMOperation(str, Enum):
    """CRM operations."""
    CREATE_CONTACT = "create_contact"
    UPDATE_CONTACT = "update_contact"
    CREATE_DEAL = "create_deal"
    UPDATE_DEAL = "update_deal"
    WEBHOOK = "webhook"


class CRMSyncStatus(str, Enum):
    """CRM sync status."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class CRMSyncResult:
    """Result of a CRM sync operation."""
    success: bool
    external_id: Optional[str] = None
    response_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    should_retry: bool = False
    operation: CRMOperation = CRMOperation.CREATE_CONTACT
    request_payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "success": self.success,
            "external_id": self.external_id,
            "response_code": self.response_code,
            "response_body": self.response_body[:1000] if self.response_body else None,
            "error_message": self.error_message,
            "should_retry": self.should_retry,
            "operation": self.operation.value if isinstance(self.operation, CRMOperation) else self.operation,
        }


@dataclass
class CRMConfig:
    """CRM configuration from project output_config."""
    enabled: bool = False
    provider: str = "hubspot"
    credentials_key: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    field_mapping: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CRMConfig":
        """Create from output_config['crm'] dictionary."""
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            provider=data.get("provider", "hubspot"),
            credentials_key=data.get("credentials_key"),
            config=data.get("config", {}),
            field_mapping=data.get("field_mapping", {}),
        )


class BaseCRMProvider(ABC):
    """
    Abstract base class for CRM integrations.

    All CRM providers must implement:
    - create_contact: Create a contact/lead in the CRM
    - test_connection: Verify credentials and connectivity

    Optional methods:
    - create_deal: Create a deal/opportunity linked to contact
    - update_contact: Update existing contact
    """

    provider_name: str = "unknown"

    # Retry configuration
    RETRYABLE_STATUS_CODES: List[int] = [429, 500, 502, 503, 504]

    @abstractmethod
    async def create_contact(
        self,
        data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Create a contact in the CRM.

        Args:
            data: Mapped contact data
            config: Provider-specific configuration

        Returns:
            CRMSyncResult with success status and external_id
        """
        pass

    async def create_deal(
        self,
        contact_id: str,
        data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Create a deal/opportunity linked to a contact.

        Args:
            contact_id: External ID of the associated contact
            data: Deal data
            config: Provider-specific configuration

        Returns:
            CRMSyncResult with success status
        """
        return CRMSyncResult(
            success=False,
            error_message="create_deal not implemented for this provider",
            operation=CRMOperation.CREATE_DEAL,
        )

    async def update_contact(
        self,
        contact_id: str,
        data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Update an existing contact.

        Args:
            contact_id: External ID of the contact
            data: Updated contact data
            config: Provider-specific configuration

        Returns:
            CRMSyncResult with success status
        """
        return CRMSyncResult(
            success=False,
            error_message="update_contact not implemented for this provider",
            operation=CRMOperation.UPDATE_CONTACT,
        )

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Verify credentials and connectivity.

        Returns:
            True if connection is successful
        """
        pass

    def is_retryable_error(self, status_code: Optional[int]) -> bool:
        """Check if the error is retryable based on status code."""
        if status_code is None:
            return True  # Network errors are retryable
        return status_code in self.RETRYABLE_STATUS_CODES

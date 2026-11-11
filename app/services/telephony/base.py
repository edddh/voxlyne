"""
Voxlyne - Telephony Base Classes

Abstract base class and types for standalone telephony/SIP-trunk providers.

Until now telephony was fully delegated into whichever voice engine owned it
(OpenAI Realtime uses OpenAI's own SIP gateway directly; Vapi owns its
internal Twilio bridge) - there was no interface analogous to
BaseCRMProvider/BaseCalendarProvider. The new LiveKit and Zadarma-SIP-trunk
providers ported from earlier-prototype need real standalone SIP-trunk/dispatch-rule
management decoupled from any specific voice/LLM engine, hence this ABC.

twilio_client.py is intentionally NOT wrapped in this interface: it remains a
thin REST helper used either directly (call status/number lookups) or inside
Vapi's own bridge, per its existing docstring.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TelephonyProvider(str, Enum):
    """Supported standalone telephony/SIP-trunk providers."""
    LIVEKIT = "livekit"
    ZADARMA = "zadarma"


@dataclass
class TelephonyConfig:
    """Telephony configuration for a project."""
    enabled: bool = False
    provider: str = "livekit"
    credentials_key: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TelephonyConfig":
        """Create from projects.voice_provider_config['telephony'] dictionary."""
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            provider=data.get("provider", "livekit"),
            credentials_key=data.get("credentials_key"),
            config=data.get("config", {}),
        )


@dataclass
class ProvisionResult:
    """Result of provisioning an inbound route (SIP trunk, dispatch rule, ...)."""
    success: bool
    external_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "external_id": self.external_id,
            "details": self.details,
            "error_message": self.error_message,
        }


class BaseTelephonyProvider(ABC):
    """
    Abstract base class for standalone telephony/SIP-trunk providers.

    All telephony providers must implement:
    - provision_inbound_route: ensure inbound calls for a project reach the
      right runtime worker (LiveKit dispatch rule, Zadarma SIP registration, ...)
    - test_connection: verify credentials/connectivity

    Optional:
    - deprovision_inbound_route: tear down what provision_inbound_route created
    """

    provider_name: str = "unknown"

    @abstractmethod
    async def provision_inbound_route(
        self,
        project_id: str,
        credentials: Dict[str, str],
        config: Dict[str, Any],
    ) -> ProvisionResult:
        """
        Ensure an inbound call for this project is routed to the correct
        runtime worker, with enough metadata (tenant_id/project_id) attached
        that the worker can resolve which project answered the call.

        Args:
            project_id: UUID (as str) of the project to provision routing for
            credentials: Decrypted provider credentials (see CredentialsManager)
            config: Provider-specific configuration (e.g. agent name, number)

        Returns:
            ProvisionResult with the external route/trunk/dispatch-rule id
        """
        raise NotImplementedError

    async def deprovision_inbound_route(
        self,
        project_id: str,
        credentials: Dict[str, str],
        external_id: str,
    ) -> bool:
        """Tear down a previously provisioned inbound route. Optional override."""
        return False

    @abstractmethod
    async def test_connection(self, credentials: Dict[str, str]) -> bool:
        """Verify credentials and connectivity."""
        raise NotImplementedError

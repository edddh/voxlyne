"""
Ascolta - Calendar Base Classes

Abstract base class and types for calendar integrations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class CalendarProviderType(str, Enum):
    """Supported calendar providers."""
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class EventStatus(str, Enum):
    """Calendar event status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CalendarSlot:
    """Represents an available time slot."""
    start: datetime
    end: datetime
    duration_minutes: int = 30

    def to_display_string(self, locale: str = "it") -> str:
        """Format slot for voice/display."""
        if locale == "it":
            day_names = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
            day_name = day_names[self.start.weekday()]
            return f"{day_name} {self.start.strftime('%d/%m')} alle {self.start.strftime('%H:%M')}"
        return f"{self.start.strftime('%A %d/%m at %H:%M')}"


@dataclass
class CalendarEvent:
    """Represents a calendar event."""
    title: str
    start: datetime
    end: datetime
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: List[str] = field(default_factory=list)
    organizer_email: Optional[str] = None
    calendar_id: str = "primary"
    timezone: str = "Europe/Rome"

    # Set after creation
    external_id: Optional[str] = None
    event_link: Optional[str] = None
    status: EventStatus = EventStatus.PENDING


@dataclass
class CalendarConfig:
    """Calendar configuration from project output_config."""
    enabled: bool = False
    provider: str = "google"
    calendar_id: str = "primary"
    default_duration_minutes: int = 30
    slot_lookahead_days: int = 14
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    working_days: List[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    timezone: str = "Europe/Rome"
    buffer_minutes: int = 15
    event_template: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CalendarConfig":
        """Create from output_config['calendar'] dictionary."""
        if not data:
            return cls()

        config = data.get("config", {})
        return cls(
            enabled=data.get("enabled", False),
            provider=data.get("provider", "google"),
            calendar_id=data.get("calendar_id", "primary"),
            default_duration_minutes=config.get("default_duration_minutes", 30),
            slot_lookahead_days=config.get("slot_lookahead_days", 14),
            working_hours_start=config.get("working_hours_start", "09:00"),
            working_hours_end=config.get("working_hours_end", "18:00"),
            working_days=config.get("working_days", [1, 2, 3, 4, 5]),
            timezone=config.get("timezone", "Europe/Rome"),
            buffer_minutes=config.get("buffer_minutes", 15),
            event_template=data.get("event_template", {}),
        )


@dataclass
class CalendarResult:
    """Result of a calendar operation."""
    success: bool
    event: Optional[CalendarEvent] = None
    external_id: Optional[str] = None
    event_link: Optional[str] = None
    error_message: Optional[str] = None
    should_retry: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "success": self.success,
            "external_id": self.external_id,
            "event_link": self.event_link,
            "error_message": self.error_message,
        }


class BaseCalendarProvider(ABC):
    """
    Abstract base class for calendar integrations.

    All calendar providers must implement:
    - get_available_slots: Find available time slots
    - create_event: Create a calendar event
    - cancel_event: Cancel an existing event
    - test_connection: Verify OAuth tokens work
    """

    provider_name: str = "unknown"

    @abstractmethod
    async def get_available_slots(
        self,
        calendar_id: str,
        start_date: datetime,
        end_date: datetime,
        duration_minutes: int,
        config: CalendarConfig,
    ) -> List[CalendarSlot]:
        """
        Find available time slots in the calendar.

        Args:
            calendar_id: Calendar to check (e.g., "primary")
            start_date: Start of search range
            end_date: End of search range
            duration_minutes: Required slot duration
            config: Calendar configuration

        Returns:
            List of available slots
        """
        pass

    @abstractmethod
    async def create_event(
        self,
        event: CalendarEvent,
        send_invites: bool = True,
    ) -> CalendarResult:
        """
        Create a calendar event.

        Args:
            event: Event details
            send_invites: Whether to send email invites to attendees

        Returns:
            CalendarResult with event ID and link
        """
        pass

    @abstractmethod
    async def cancel_event(
        self,
        calendar_id: str,
        event_id: str,
        notify_attendees: bool = True,
    ) -> CalendarResult:
        """
        Cancel an existing event.

        Args:
            calendar_id: Calendar containing the event
            event_id: External event ID
            notify_attendees: Whether to notify attendees

        Returns:
            CalendarResult with success status
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Verify OAuth tokens and connectivity.

        Returns:
            True if connection is successful
        """
        pass

    async def refresh_token(self) -> bool:
        """
        Refresh OAuth access token using refresh token.

        Returns:
            True if refresh was successful
        """
        return False

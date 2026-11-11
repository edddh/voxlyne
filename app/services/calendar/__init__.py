"""
Voxlyne - Calendar Integration Module

This module provides calendar scheduling capabilities:
- Google Calendar integration with OAuth2
- Microsoft 365/Outlook integration with Graph API
- Slot availability checking
- Event creation with attendees
- Invite sending
"""

from app.services.calendar.base import (
    CalendarProviderType,
    CalendarEvent,
    CalendarSlot,
    CalendarConfig,
)
from app.services.calendar.scheduler import CalendarScheduler

__all__ = [
    "CalendarProviderType",
    "CalendarEvent",
    "CalendarSlot",
    "CalendarConfig",
    "CalendarScheduler",
]

"""
Ascolta - Calendar Providers

Available providers:
- GoogleCalendarProvider: Google Calendar with OAuth2
- MicrosoftCalendarProvider: Microsoft 365/Outlook with Graph API
"""

from app.services.calendar.providers.google import GoogleCalendarProvider
from app.services.calendar.providers.microsoft import MicrosoftCalendarProvider

__all__ = [
    "GoogleCalendarProvider",
    "MicrosoftCalendarProvider",
]

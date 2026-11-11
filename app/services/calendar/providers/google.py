"""
Voxlyne - Google Calendar Provider

Google Calendar integration using OAuth2 and Calendar API v3.
https://developers.google.com/calendar/api/v3/reference
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

import httpx

from app.services.calendar.base import (
    BaseCalendarProvider,
    CalendarConfig,
    CalendarEvent,
    CalendarResult,
    CalendarSlot,
    EventStatus,
)

logger = logging.getLogger(__name__)


class GoogleCalendarProvider(BaseCalendarProvider):
    """
    Google Calendar integration.

    Features:
    - OAuth2 authentication
    - FreeBusy query for availability
    - Event creation with attendees
    - Send calendar invites
    """

    provider_name = "google"
    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize Google Calendar provider.

        Args:
            access_token: OAuth2 access token
            refresh_token: OAuth2 refresh token (for token refresh)
            client_id: OAuth2 client ID (for token refresh)
            client_secret: OAuth2 client secret (for token refresh)
            timeout: Request timeout in seconds
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

    def _get_headers(self) -> dict:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_available_slots(
        self,
        calendar_id: str,
        start_date: datetime,
        end_date: datetime,
        duration_minutes: int,
        config: CalendarConfig,
    ) -> List[CalendarSlot]:
        """
        Find available time slots using FreeBusy API.

        Args:
            calendar_id: Calendar to check
            start_date: Start of search range
            end_date: End of search range
            duration_minutes: Required slot duration
            config: Calendar configuration

        Returns:
            List of available CalendarSlots
        """
        url = f"{self.BASE_URL}/freeBusy"

        # Query busy times
        payload = {
            "timeMin": start_date.isoformat() + "Z",
            "timeMax": end_date.isoformat() + "Z",
            "timeZone": config.timezone,
            "items": [{"id": calendar_id}],
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code != 200:
                    logger.error(f"FreeBusy query failed: {response.status_code}")
                    return []

                data = response.json()
                busy_times = data.get("calendars", {}).get(calendar_id, {}).get("busy", [])

                # Convert busy times to datetime objects
                busy_periods = []
                for busy in busy_times:
                    start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
                    busy_periods.append((start, end))

                # Find available slots
                return self._find_available_slots(
                    start_date=start_date,
                    end_date=end_date,
                    busy_periods=busy_periods,
                    duration_minutes=duration_minutes,
                    config=config,
                )

        except Exception as e:
            logger.error(f"Error getting available slots: {e}")
            return []

    def _find_available_slots(
        self,
        start_date: datetime,
        end_date: datetime,
        busy_periods: List[tuple],
        duration_minutes: int,
        config: CalendarConfig,
    ) -> List[CalendarSlot]:
        """Find available slots given busy periods."""
        slots = []
        current = start_date

        # Parse working hours
        work_start_h, work_start_m = map(int, config.working_hours_start.split(":"))
        work_end_h, work_end_m = map(int, config.working_hours_end.split(":"))

        slot_duration = timedelta(minutes=duration_minutes)
        buffer = timedelta(minutes=config.buffer_minutes)

        while current < end_date and len(slots) < 10:  # Limit to 10 slots
            # Check if it's a working day
            # weekday(): Monday=0, Sunday=6 ; config uses 1=Mon, 7=Sun
            if (current.weekday() + 1) not in config.working_days:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            # Set to working hours start if before
            work_start = current.replace(hour=work_start_h, minute=work_start_m, second=0, microsecond=0)
            work_end = current.replace(hour=work_end_h, minute=work_end_m, second=0, microsecond=0)

            if current < work_start:
                current = work_start
            elif current >= work_end:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            # Check slot fits in working hours
            slot_end = current + slot_duration
            if slot_end > work_end:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            # Check against busy periods
            is_available = True
            for busy_start, busy_end in busy_periods:
                # Add buffer around busy times
                busy_start_buffered = busy_start - buffer
                busy_end_buffered = busy_end + buffer

                if not (slot_end <= busy_start_buffered or current >= busy_end_buffered):
                    is_available = False
                    # Skip to end of busy period
                    current = busy_end_buffered
                    break

            if is_available:
                slots.append(CalendarSlot(
                    start=current,
                    end=slot_end,
                    duration_minutes=duration_minutes,
                ))
                # Move to next potential slot with buffer
                current = slot_end + buffer
            # else: current was already updated in the loop

        return slots

    async def create_event(
        self,
        event: CalendarEvent,
        send_invites: bool = True,
    ) -> CalendarResult:
        """
        Create a Google Calendar event.

        Args:
            event: Event details
            send_invites: Whether to send email invites

        Returns:
            CalendarResult with event ID and link
        """
        url = f"{self.BASE_URL}/calendars/{event.calendar_id}/events"
        params = {"sendUpdates": "all" if send_invites else "none"}

        # Build event payload
        payload = {
            "summary": event.title,
            "description": event.description,
            "location": event.location,
            "start": {
                "dateTime": event.start.isoformat(),
                "timeZone": event.timezone,
            },
            "end": {
                "dateTime": event.end.isoformat(),
                "timeZone": event.timezone,
            },
            "attendees": [{"email": email} for email in event.attendees],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},  # 1 day before
                    {"method": "popup", "minutes": 30},       # 30 min before
                ],
            },
        }

        if event.organizer_email:
            payload["organizer"] = {"email": event.organizer_email}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    json=payload,
                )

                if response.status_code == 200:
                    data = response.json()
                    event.external_id = data.get("id")
                    event.event_link = data.get("htmlLink")
                    event.status = EventStatus.CONFIRMED

                    logger.info(f"Google Calendar event created: {event.external_id}")

                    return CalendarResult(
                        success=True,
                        event=event,
                        external_id=event.external_id,
                        event_link=event.event_link,
                    )

                else:
                    error_msg = self._extract_error(response)
                    logger.error(f"Failed to create event: {error_msg}")

                    return CalendarResult(
                        success=False,
                        error_message=error_msg,
                        should_retry=response.status_code in [429, 500, 503],
                    )

        except httpx.TimeoutException:
            return CalendarResult(
                success=False,
                error_message="Request timeout",
                should_retry=True,
            )

        except Exception as e:
            logger.error(f"Error creating event: {e}")
            return CalendarResult(
                success=False,
                error_message=str(e),
                should_retry=False,
            )

    async def cancel_event(
        self,
        calendar_id: str,
        event_id: str,
        notify_attendees: bool = True,
    ) -> CalendarResult:
        """
        Cancel (delete) a Google Calendar event.

        Args:
            calendar_id: Calendar containing the event
            event_id: Event ID to cancel
            notify_attendees: Whether to notify attendees

        Returns:
            CalendarResult with success status
        """
        url = f"{self.BASE_URL}/calendars/{calendar_id}/events/{event_id}"
        params = {"sendUpdates": "all" if notify_attendees else "none"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(
                    url,
                    headers=self._get_headers(),
                    params=params,
                )

                if response.status_code == 204:
                    logger.info(f"Google Calendar event cancelled: {event_id}")
                    return CalendarResult(success=True)

                else:
                    error_msg = self._extract_error(response)
                    return CalendarResult(
                        success=False,
                        error_message=error_msg,
                    )

        except Exception as e:
            logger.error(f"Error cancelling event: {e}")
            return CalendarResult(
                success=False,
                error_message=str(e),
            )

    async def test_connection(self) -> bool:
        """
        Test Google Calendar API connectivity.

        Returns:
            True if connection is successful
        """
        url = f"{self.BASE_URL}/users/me/calendarList"
        params = {"maxResults": 1}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                )

                if response.status_code == 200:
                    logger.info("Google Calendar connection test successful")
                    return True

                logger.warning(f"Google Calendar test failed: {response.status_code}")
                return False

        except Exception as e:
            logger.warning(f"Google Calendar connection test error: {e}")
            return False

    async def refresh_token(self) -> bool:
        """
        Refresh OAuth2 access token.

        Returns:
            True if refresh was successful
        """
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return False

        url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, data=payload)

                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    logger.info("Google OAuth token refreshed")
                    return True

                logger.error(f"Token refresh failed: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False

    def _extract_error(self, response: httpx.Response) -> str:
        """Extract error message from response."""
        try:
            data = response.json()
            error = data.get("error", {})
            if isinstance(error, dict):
                return error.get("message", f"Error {response.status_code}")
            return str(error)
        except Exception:
            return f"Error {response.status_code}: {response.text[:200]}"

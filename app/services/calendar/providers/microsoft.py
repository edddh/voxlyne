"""
Voxlyne - Microsoft 365 Calendar Provider

Microsoft Graph API integration for Outlook Calendar.
https://learn.microsoft.com/en-us/graph/api/resources/calendar
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


class MicrosoftCalendarProvider(BaseCalendarProvider):
    """
    Microsoft 365/Outlook Calendar integration.

    Features:
    - OAuth2 authentication via Graph API
    - Schedule availability query
    - Event creation with attendees
    - Teams meeting integration (optional)
    """

    provider_name = "microsoft"
    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize Microsoft Calendar provider.

        Args:
            access_token: OAuth2 access token
            refresh_token: OAuth2 refresh token
            client_id: Azure AD application ID
            client_secret: Azure AD client secret
            tenant_id: Azure AD tenant ID
            timeout: Request timeout in seconds
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id or "common"
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
        Find available time slots using getSchedule API.

        Args:
            calendar_id: User email or calendar ID
            start_date: Start of search range
            end_date: End of search range
            duration_minutes: Required slot duration
            config: Calendar configuration

        Returns:
            List of available CalendarSlots
        """
        url = f"{self.BASE_URL}/me/calendar/getSchedule"

        payload = {
            "schedules": [calendar_id],
            "startTime": {
                "dateTime": start_date.isoformat(),
                "timeZone": config.timezone,
            },
            "endTime": {
                "dateTime": end_date.isoformat(),
                "timeZone": config.timezone,
            },
            "availabilityViewInterval": duration_minutes,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code != 200:
                    logger.error(f"getSchedule query failed: {response.status_code}")
                    return []

                data = response.json()
                schedules = data.get("value", [])

                if not schedules:
                    return []

                schedule_info = schedules[0]
                busy_times = schedule_info.get("scheduleItems", [])

                # Convert to busy periods
                busy_periods = []
                for item in busy_times:
                    if item.get("status") in ["busy", "tentative", "oof"]:
                        start = datetime.fromisoformat(
                            item["start"]["dateTime"].replace("Z", "+00:00")
                        )
                        end = datetime.fromisoformat(
                            item["end"]["dateTime"].replace("Z", "+00:00")
                        )
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

        while current < end_date and len(slots) < 10:
            # Check working day (Microsoft uses same weekday convention)
            if (current.weekday() + 1) not in config.working_days:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            work_start = current.replace(hour=work_start_h, minute=work_start_m, second=0, microsecond=0)
            work_end = current.replace(hour=work_end_h, minute=work_end_m, second=0, microsecond=0)

            if current < work_start:
                current = work_start
            elif current >= work_end:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            slot_end = current + slot_duration
            if slot_end > work_end:
                current = current.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            is_available = True
            for busy_start, busy_end in busy_periods:
                busy_start_buffered = busy_start - buffer
                busy_end_buffered = busy_end + buffer

                if not (slot_end <= busy_start_buffered or current >= busy_end_buffered):
                    is_available = False
                    current = busy_end_buffered
                    break

            if is_available:
                slots.append(CalendarSlot(
                    start=current,
                    end=slot_end,
                    duration_minutes=duration_minutes,
                ))
                current = slot_end + buffer

        return slots

    async def create_event(
        self,
        event: CalendarEvent,
        send_invites: bool = True,
    ) -> CalendarResult:
        """
        Create an Outlook Calendar event.

        Args:
            event: Event details
            send_invites: Whether to send email invites

        Returns:
            CalendarResult with event ID and link
        """
        url = f"{self.BASE_URL}/me/events"

        # Build event payload (Microsoft Graph format)
        payload = {
            "subject": event.title,
            "body": {
                "contentType": "text",
                "content": event.description or "",
            },
            "start": {
                "dateTime": event.start.isoformat(),
                "timeZone": event.timezone,
            },
            "end": {
                "dateTime": event.end.isoformat(),
                "timeZone": event.timezone,
            },
            "location": {
                "displayName": event.location or "",
            },
            "attendees": [
                {
                    "emailAddress": {"address": email},
                    "type": "required",
                }
                for email in event.attendees
            ],
            "isReminderOn": True,
            "reminderMinutesBeforeStart": 30,
        }

        # Don't send invites if requested
        if not send_invites:
            payload["responseRequested"] = False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 201:
                    data = response.json()
                    event.external_id = data.get("id")
                    event.event_link = data.get("webLink")
                    event.status = EventStatus.CONFIRMED

                    logger.info(f"Microsoft Calendar event created: {event.external_id}")

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
            )

    async def cancel_event(
        self,
        calendar_id: str,
        event_id: str,
        notify_attendees: bool = True,
    ) -> CalendarResult:
        """
        Cancel (delete) an Outlook event.

        Args:
            calendar_id: Not used for Microsoft (uses /me)
            event_id: Event ID to cancel
            notify_attendees: Whether to notify attendees

        Returns:
            CalendarResult with success status
        """
        # First cancel the event (sends cancellation to attendees)
        if notify_attendees:
            cancel_url = f"{self.BASE_URL}/me/events/{event_id}/cancel"
            payload = {"comment": "Appuntamento annullato"}

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        cancel_url,
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 202:
                        logger.info(f"Microsoft Calendar event cancelled: {event_id}")
                        return CalendarResult(success=True)

            except Exception as e:
                logger.warning(f"Cancel notification failed: {e}")

        # Delete the event
        delete_url = f"{self.BASE_URL}/me/events/{event_id}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(
                    delete_url,
                    headers=self._get_headers(),
                )

                if response.status_code == 204:
                    logger.info(f"Microsoft Calendar event deleted: {event_id}")
                    return CalendarResult(success=True)

                return CalendarResult(
                    success=False,
                    error_message=self._extract_error(response),
                )

        except Exception as e:
            logger.error(f"Error deleting event: {e}")
            return CalendarResult(
                success=False,
                error_message=str(e),
            )

    async def test_connection(self) -> bool:
        """
        Test Microsoft Graph API connectivity.

        Returns:
            True if connection is successful
        """
        url = f"{self.BASE_URL}/me/calendars"
        params = {"$top": 1}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                )

                if response.status_code == 200:
                    logger.info("Microsoft Calendar connection test successful")
                    return True

                logger.warning(f"Microsoft Calendar test failed: {response.status_code}")
                return False

        except Exception as e:
            logger.warning(f"Microsoft Calendar connection test error: {e}")
            return False

    async def refresh_token(self) -> bool:
        """
        Refresh OAuth2 access token.

        Returns:
            True if refresh was successful
        """
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return False

        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
            "scope": "https://graph.microsoft.com/.default",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, data=payload)

                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    if "refresh_token" in data:
                        self.refresh_token = data["refresh_token"]
                    logger.info("Microsoft OAuth token refreshed")
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

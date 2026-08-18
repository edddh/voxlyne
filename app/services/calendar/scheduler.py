"""
Ascolta - Calendar Scheduler

Orchestrates calendar operations: slot finding, event creation, and tracking.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import get_settings
from app.database.db import get_database
from app.services.calendar.base import (
    BaseCalendarProvider,
    CalendarConfig,
    CalendarEvent,
    CalendarResult,
    CalendarSlot,
    EventStatus,
)
from app.services.calendar.providers.google import GoogleCalendarProvider
from app.services.calendar.providers.microsoft import MicrosoftCalendarProvider
from app.services.encryption import decrypt

logger = logging.getLogger(__name__)


class CalendarScheduler:
    """
    Orchestrates calendar scheduling for completed interviews.

    Responsibilities:
    - Fetch calendar configuration from project
    - Get OAuth tokens from database
    - Find available slots
    - Create events with attendees
    - Track events in database
    """

    def __init__(self):
        self.settings = get_settings()

    async def get_available_slots(
        self,
        call_id: UUID,
        num_slots: int = 3,
    ) -> List[CalendarSlot]:
        """
        Get available appointment slots for a call.

        Args:
            call_id: UUID of the call
            num_slots: Maximum number of slots to return

        Returns:
            List of available CalendarSlots
        """
        # 1. Get calendar config
        config = await self._get_calendar_config(call_id)
        if not config or not config.enabled:
            logger.debug(f"Calendar not enabled for call {call_id}")
            return []

        # 2. Get provider with tokens
        provider = await self._get_provider(call_id, config.provider)
        if not provider:
            logger.warning(f"No calendar provider available for call {call_id}")
            return []

        # 3. Calculate search range
        now = datetime.now(timezone.utc)
        start_date = now + timedelta(days=1)  # Start tomorrow
        end_date = now + timedelta(days=config.slot_lookahead_days)

        # 4. Get slots from provider
        try:
            slots = await provider.get_available_slots(
                calendar_id=config.calendar_id,
                start_date=start_date,
                end_date=end_date,
                duration_minutes=config.default_duration_minutes,
                config=config,
            )

            return slots[:num_slots]

        except Exception as e:
            logger.error(f"Error getting slots for call {call_id}: {e}")
            return []

    async def schedule_appointment(
        self,
        call_id: UUID,
        slot: CalendarSlot,
        candidate_data: Dict[str, Any],
        hr_email: Optional[str] = None,
    ) -> CalendarResult:
        """
        Schedule an appointment for the given slot.

        Args:
            call_id: UUID of the call
            slot: Selected time slot
            candidate_data: Candidate info (name, email, phone)
            hr_email: HR email for the meeting (optional, uses config default)

        Returns:
            CalendarResult with event details
        """
        db = get_database()

        # 1. Get calendar config
        config = await self._get_calendar_config(call_id)
        if not config or not config.enabled:
            return CalendarResult(
                success=False,
                error_message="Calendar not enabled for this project",
            )

        # 2. Get provider
        provider = await self._get_provider(call_id, config.provider)
        if not provider:
            return CalendarResult(
                success=False,
                error_message="Calendar provider not configured",
            )

        # 3. Build event from template
        event = self._build_event(
            slot=slot,
            candidate_data=candidate_data,
            hr_email=hr_email,
            config=config,
        )

        # 4. Create event
        try:
            result = await provider.create_event(event, send_invites=True)

            if result.success:
                # 5. Save to database
                await self._save_calendar_event(
                    call_id=call_id,
                    event=result.event or event,
                    result=result,
                    config=config,
                )

                logger.info(f"Appointment scheduled for call {call_id}")

            return result

        except Exception as e:
            logger.error(f"Error scheduling appointment for call {call_id}: {e}")
            return CalendarResult(
                success=False,
                error_message=str(e),
            )

    async def cancel_appointment(
        self,
        call_id: UUID,
        notify_attendees: bool = True,
    ) -> CalendarResult:
        """
        Cancel a scheduled appointment.

        Args:
            call_id: UUID of the call
            notify_attendees: Whether to notify attendees

        Returns:
            CalendarResult with success status
        """
        db = get_database()

        # 1. Get existing event
        event_record = await db.fetch_one(
            """
            SELECT ce.*, r.call_id
            FROM calendar_events ce
            JOIN records r ON ce.record_id = r.id
            WHERE r.call_id = :call_id AND ce.status != 'cancelled'
            ORDER BY ce.created_at DESC
            LIMIT 1
            """,
            {"call_id": str(call_id)},
        )

        if not event_record:
            return CalendarResult(
                success=False,
                error_message="No active appointment found",
            )

        # 2. Get provider
        config = await self._get_calendar_config(call_id)
        provider = await self._get_provider(call_id, event_record["provider"])

        if not provider:
            return CalendarResult(
                success=False,
                error_message="Calendar provider not available",
            )

        # 3. Cancel event
        try:
            result = await provider.cancel_event(
                calendar_id=event_record["calendar_id"] or "primary",
                event_id=event_record["external_event_id"],
                notify_attendees=notify_attendees,
            )

            if result.success:
                # Update database
                await db.execute(
                    """
                    UPDATE calendar_events
                    SET status = 'cancelled', updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {
                        "id": event_record["id"],
                        "updated_at": datetime.now(timezone.utc),
                    },
                )

                await db.execute(
                    """
                    UPDATE records
                    SET appointment_scheduled = FALSE, updated_at = :updated_at
                    WHERE call_id = :call_id
                    """,
                    {
                        "call_id": str(call_id),
                        "updated_at": datetime.now(timezone.utc),
                    },
                )

                logger.info(f"Appointment cancelled for call {call_id}")

            return result

        except Exception as e:
            logger.error(f"Error cancelling appointment: {e}")
            return CalendarResult(
                success=False,
                error_message=str(e),
            )

    async def _get_calendar_config(self, call_id: UUID) -> Optional[CalendarConfig]:
        """Fetch calendar config from project_calendar_config table (M4+)."""
        db = get_database()

        # Get project_id from call
        call_data = await db.fetch_one(
            "SELECT project_id FROM calls WHERE id = :call_id",
            {"call_id": str(call_id)}
        )

        if not call_data or not call_data["project_id"]:
            logger.warning(f"Call {call_id} has no project_id, calendar sync skipped")
            return None

        # Query project_calendar_config (M4+)
        config = await db.fetch_one(
            """
            SELECT enabled, provider, access_token_encrypted, refresh_token_encrypted,
                   expires_at, calendar_id, timezone, config
            FROM project_calendar_config
            WHERE project_id = :project_id AND enabled = TRUE
            """,
            {"project_id": str(call_data["project_id"])}
        )

        if not config:
            logger.info(f"No calendar config for project {call_data['project_id']}, calendar sync skipped")
            return None

        # Decrypt OAuth tokens
        from app.services.encryption import decrypt

        credentials = {}
        if config["access_token_encrypted"]:
            credentials["access_token"] = decrypt(config["access_token_encrypted"])
        if config["refresh_token_encrypted"]:
            credentials["refresh_token"] = decrypt(config["refresh_token_encrypted"])

        return CalendarConfig(
            enabled=True,
            provider=config["provider"],
            credentials=credentials,
            calendar_id=config["calendar_id"] or "primary",
            timezone=config["timezone"] or "Europe/Rome",
            config=config["config"] or {}
        )

    async def _get_provider(
        self,
        call_id: UUID,
        provider_name: str,
    ) -> Optional[BaseCalendarProvider]:
        """Get calendar provider with OAuth tokens."""
        db = get_database()

        # Get project_id for this call
        call = await db.fetch_one(
            "SELECT project_id FROM calls WHERE id = :call_id",
            {"call_id": str(call_id)},
        )

        if not call or not call["project_id"]:
            return None

        # Get tokens from database. Reads project_calendar_config, NOT the
        # older calendar_tokens table (migrations/004_calendar_integration.sql)
        # this used to query - project_calendar_config is what
        # app/routers/project_config.py's save_calendar_config() actually
        # writes to (verified 18/08: calendar_tokens has no writer anywhere
        # in the codebase, only this now-fixed reader - a token saved from
        # the admin UI was never going to be found here, silently falling
        # through to the .env fallback below on every real booking attempt).
        token_record = await db.fetch_one(
            """
            SELECT access_token_encrypted, refresh_token_encrypted, expires_at
            FROM project_calendar_config
            WHERE project_id = :project_id
              AND provider = :provider
              AND enabled = TRUE
            """,
            {
                "project_id": str(call["project_id"]),
                "provider": provider_name,
            },
        )

        if token_record:
            # Tokens are written encrypted (see app/routers/project_config.py's
            # encrypt() call before the INSERT/UPDATE) - this was reading them
            # back as plain text, which would hand the calendar provider a
            # Fernet ciphertext instead of a real OAuth token on every booking
            # attempt that actually has a stored token (18/08 fix).
            access_token = decrypt(token_record["access_token_encrypted"])
            refresh_token = decrypt(token_record["refresh_token_encrypted"])
        else:
            # Fall back to environment variables
            if provider_name == "google":
                access_token = self.settings.google_calendar_access_token
                refresh_token = self.settings.google_calendar_refresh_token
            elif provider_name == "microsoft":
                access_token = self.settings.ms_graph_access_token
                refresh_token = self.settings.ms_graph_refresh_token
            else:
                return None

        if not access_token:
            return None

        # Create provider
        if provider_name == "google":
            return GoogleCalendarProvider(
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=self.settings.google_calendar_client_id,
                client_secret=self.settings.google_calendar_client_secret,
            )
        elif provider_name == "microsoft":
            return MicrosoftCalendarProvider(
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=self.settings.ms_graph_client_id,
                client_secret=self.settings.ms_graph_client_secret,
                tenant_id=self.settings.ms_graph_tenant_id,
            )

        return None

    def _build_event(
        self,
        slot: CalendarSlot,
        candidate_data: Dict[str, Any],
        hr_email: Optional[str],
        config: CalendarConfig,
    ) -> CalendarEvent:
        """Build calendar event from template and data."""
        template = config.event_template or {}

        # Get candidate info
        candidate_name = candidate_data.get("candidate_name", "Candidato")
        candidate_email = candidate_data.get("email")
        role = candidate_data.get("role_targets", [""])[0] if candidate_data.get("role_targets") else ""

        # Build title and description from template
        title = template.get("title", "Colloquio HR - {candidate_name}")
        title = title.format(candidate_name=candidate_name, role=role)

        description = template.get("description", "Colloquio con {candidate_name}")
        description = description.format(candidate_name=candidate_name, role=role)

        location = template.get("location", "")

        # Build attendee list
        attendees = []
        if hr_email:
            attendees.append(hr_email)
        if candidate_email:
            attendees.append(candidate_email)

        return CalendarEvent(
            title=title,
            start=slot.start,
            end=slot.end,
            description=description,
            location=location,
            attendees=attendees,
            calendar_id=config.calendar_id,
            timezone=config.timezone,
        )

    async def _save_calendar_event(
        self,
        call_id: UUID,
        event: CalendarEvent,
        result: CalendarResult,
        config: CalendarConfig,
    ) -> None:
        """Save calendar event to database."""
        db = get_database()

        # Get record_id for this call
        record = await db.fetch_one(
            "SELECT id FROM records WHERE call_id = :call_id",
            {"call_id": str(call_id)},
        )

        record_id = record["id"] if record else None

        # Insert event record
        event_row = await db.fetch_one(
            """
            INSERT INTO calendar_events (
                record_id, call_id, provider, calendar_id,
                external_event_id, event_link, scheduled_at,
                duration_minutes, timezone, organizer_email,
                attendee_emails, status, invite_sent, invite_sent_at,
                created_at
            ) VALUES (
                :record_id, :call_id, :provider, :calendar_id,
                :external_event_id, :event_link, :scheduled_at,
                :duration_minutes, :timezone, :organizer_email,
                :attendee_emails, :status, TRUE, :invite_sent_at,
                :created_at
            )
            RETURNING id
            """,
            {
                "record_id": record_id,
                "call_id": str(call_id),
                "provider": config.provider,
                "calendar_id": config.calendar_id,
                "external_event_id": result.external_id,
                "event_link": result.event_link,
                "scheduled_at": event.start,
                "duration_minutes": (event.end - event.start).seconds // 60,
                "timezone": event.timezone,
                "organizer_email": event.organizer_email,
                "attendee_emails": event.attendees,
                "status": EventStatus.CONFIRMED.value,
                "invite_sent_at": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc),
            },
        )

        # Update record with calendar info
        if record_id:
            await db.execute(
                """
                UPDATE records
                SET calendar_event_id = :event_id,
                    appointment_scheduled = TRUE,
                    appointment_datetime = :datetime,
                    updated_at = :updated_at
                WHERE id = :record_id
                """,
                {
                    "event_id": event_row["id"],
                    "datetime": event.start,
                    "updated_at": datetime.now(timezone.utc),
                    "record_id": record_id,
                },
            )

    async def test_connection(
        self,
        provider: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> bool:
        """
        Test calendar connection with provided token.

        Args:
            provider: Provider name (google, microsoft)
            access_token: OAuth access token
            refresh_token: Optional refresh token

        Returns:
            True if connection works
        """
        if provider == "google":
            provider_instance = GoogleCalendarProvider(
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=self.settings.google_calendar_client_id,
                client_secret=self.settings.google_calendar_client_secret,
            )
        elif provider == "microsoft":
            provider_instance = MicrosoftCalendarProvider(
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=self.settings.ms_graph_client_id,
                client_secret=self.settings.ms_graph_client_secret,
                tenant_id=self.settings.ms_graph_tenant_id,
            )
        else:
            return False

        return await provider_instance.test_connection()

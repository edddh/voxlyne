"""
Ascolta - Email Service
Transactional email sender for reports and account flows.
"""

import asyncio
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmailServiceError(Exception):
    """Raised when email sending fails."""
    pass


class EmailService:
    """
    Sends emails with PDF attachments.
    Used to deliver candidate reports after interview completion.
    """

    def __init__(self):
        self.settings = get_settings()

    def is_enabled(self) -> bool:
        """Check if email service is properly configured and enabled."""
        return (
            self.settings.email_enabled
            and self.settings.smtp_host is not None
            and self.settings.email_from is not None
        )

    async def send_candidate_report(
        self,
        pdf_bytes: bytes,
        json_data: Dict[str, Any],
        call_metadata: Optional[Dict[str, Any]] = None,
        recipient: Optional[str] = None,
    ) -> bool:
        """
        Send candidate PDF report via email.

        Args:
            pdf_bytes: PDF file content
            json_data: Extracted candidate data (for subject/body)
            call_metadata: Optional call info (date, duration)
            recipient: Optional recipient override (defaults to email_to_default)

        Returns:
            True if sent successfully

        Raises:
            EmailServiceError: If sending fails
        """
        if not self.is_enabled():
            logger.warning("Email service not enabled or not configured")
            return False

        to_email = recipient or self.settings.email_to_default
        if not to_email:
            logger.error("No recipient email configured")
            return False

        try:
            # Extract candidate info from JSON
            candidate_name = json_data.get("name") or json_data.get("nome") or "Candidato"
            candidate_role = json_data.get("role") or json_data.get("ruolo") or json_data.get("position") or "Non specificato"
            candidate_phone = json_data.get("phone_number") or json_data.get("telefono") or ""

            # Build email subject
            subject = f"Colloquio: {candidate_name} - {candidate_role}"

            # Build minimal email body
            body = self._build_email_body(
                candidate_name=candidate_name,
                candidate_role=candidate_role,
                candidate_phone=candidate_phone,
                call_metadata=call_metadata,
            )

            # Build filename
            safe_name = "".join(c for c in candidate_name if c.isalnum() or c in " -_").strip()
            filename = f"Colloquio_{safe_name}.pdf" if safe_name else "Colloquio.pdf"

            # Send email
            await self._send_email(
                to_email=to_email,
                subject=subject,
                body=body,
                pdf_bytes=pdf_bytes,
                pdf_filename=filename,
            )

            logger.info(f"Email sent to {to_email}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            raise EmailServiceError(f"Email sending failed: {e}") from e

    def _build_email_body(
        self,
        candidate_name: str,
        candidate_role: str,
        candidate_phone: str,
        call_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build minimal email body text."""
        lines = [
            f"Candidato: {candidate_name}",
            f"Ruolo: {candidate_role}",
        ]

        if candidate_phone:
            lines.append(f"Telefono: {candidate_phone}")

        if call_metadata:
            # Format call date
            started_at = call_metadata.get("started_at")
            if started_at:
                from datetime import datetime
                if isinstance(started_at, str):
                    started_at = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                lines.append(f"Data colloquio: {started_at.strftime('%d/%m/%Y %H:%M')}")

            # Format duration
            duration = call_metadata.get("duration_seconds")
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                lines.append(f"Durata: {minutes}m {seconds}s")

        lines.append("")
        lines.append("In allegato il report completo.")

        return "\n".join(lines)

    async def send_password_reset_email(
        self,
        to_email: str,
        reset_url: str,
        full_name: Optional[str] = None,
    ) -> bool:
        """Send password reset email."""
        if not self.is_enabled():
            logger.warning("Email service not enabled or not configured")
            return False

        display_name = full_name or to_email
        subject = "Reset password Ascolta"
        body = self._build_password_reset_body(display_name=display_name, reset_url=reset_url)

        try:
            await self._send_email(
                to_email=to_email,
                subject=subject,
                body=body,
            )
            logger.info(f"Password reset email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send password reset email: {e}", exc_info=True)
            raise EmailServiceError(f"Password reset email sending failed: {e}") from e

    def _build_password_reset_body(self, display_name: str, reset_url: str) -> str:
        """Build plain text body for password reset."""
        return "\n".join([
            f"Ciao {display_name},",
            "",
            "Abbiamo ricevuto una richiesta di reset della password per il tuo account Ascolta.",
            "Apri questo link per impostare una nuova password:",
            reset_url,
            "",
            "Se non hai richiesto tu il reset, puoi ignorare questa email.",
        ])

    async def _send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        pdf_bytes: Optional[bytes] = None,
        pdf_filename: Optional[str] = None,
    ) -> None:
        """Send email with optional PDF attachment using SMTP."""
        # Create message
        msg = MIMEMultipart()
        msg["From"] = self.settings.email_from
        msg["To"] = to_email
        msg["Subject"] = subject

        # Attach body
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if pdf_bytes is not None and pdf_filename:
            pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=pdf_filename,
            )
            msg.attach(pdf_part)

        # Send via SMTP - offloaded to a thread (18/08 fix): smtplib is a
        # blocking, synchronous library (real network I/O - TLS handshake,
        # auth, the send itself), and this method is async but was calling
        # it inline with no executor - blocking the whole process's event
        # loop, including any live voice call being served concurrently,
        # for the entire SMTP conversation. Same bug class fixed the same
        # day in post_processor.py's OpenAI call.
        try:
            await asyncio.to_thread(self._send_via_smtp, msg, to_email)
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            raise

    def _send_via_smtp(self, msg: MIMEMultipart, to_email: str) -> None:
        smtp_security = self.settings.smtp_security.lower()

        if smtp_security == "ssl":
            server_factory = smtplib.SMTP_SSL
        else:
            server_factory = smtplib.SMTP

        with server_factory(self.settings.smtp_host, self.settings.smtp_port) as server:
            if smtp_security == "starttls":
                server.starttls()
            if self.settings.smtp_user and self.settings.smtp_password:
                server.login(self.settings.smtp_user, self.settings.smtp_password)
            server.send_message(msg)
            logger.debug(f"SMTP send complete to {to_email}")


def get_email_service() -> EmailService:
    """Get email service instance."""
    return EmailService()

"""
Ascolta - PDF Generator
Converts JSON data to beautifully formatted PDF candidate profiles
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.database.db import get_database
from app.storage.s3_client import get_s3_client

logger = logging.getLogger(__name__)


class PDFGeneratorError(Exception):
    """Raised when PDF generation fails."""
    pass


class PDFGenerator:
    """
    Generates PDF reports from structured JSON data.
    Uses Jinja2 templates and WeasyPrint for HTML to PDF conversion.
    """

    def __init__(self):
        # Setup Jinja2 environment
        template_dir = Path(__file__).parent.parent / "templates" / "pdf"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(['html', 'xml'])
        )

        self.s3_client = get_s3_client()

    async def generate_and_upload_pdf(
        self,
        call_id: UUID,
        json_data: Dict[str, Any],
        template_name: str = "candidate.html"
    ) -> str:
        """
        Generate PDF from JSON data and upload to S3.

        Args:
            call_id: UUID of the call
            json_data: Structured data extracted from transcript
            template_name: Jinja2 template filename

        Returns:
            S3 object key (path) of uploaded PDF

        Raises:
            PDFGeneratorError: If generation or upload fails
        """
        try:
            logger.info(f"Generating PDF for call {call_id}")

            # 1. Fetch call metadata
            call_metadata = await self._fetch_call_metadata(call_id)

            # 2. Fetch project slug
            project_slug = await self._fetch_project_slug(
                call_metadata.get("project_id")
            )

            # 3. Generate PDF bytes
            pdf_bytes = self.generate_pdf(
                data=json_data,
                call_metadata=call_metadata,
                template_name=template_name
            )

            # 4. Upload to S3
            s3_key = self.s3_client.upload_pdf(
                file_content=pdf_bytes,
                call_id=call_id,
                project_slug=project_slug
            )

            # 5. Update record with PDF info
            await self._update_record_pdf_info(
                call_id=call_id,
                pdf_key=s3_key
            )

            logger.info(
                f"PDF generated and uploaded for call {call_id}: {s3_key} "
                f"({len(pdf_bytes)} bytes)"
            )

            return s3_key

        except Exception as e:
            logger.error(f"Failed to generate PDF for call {call_id}: {e}", exc_info=True)
            raise PDFGeneratorError(f"PDF generation failed: {e}") from e

    def generate_pdf(
        self,
        data: Dict[str, Any],
        call_metadata: Optional[Dict[str, Any]] = None,
        template_name: str = "candidate.html"
    ) -> bytes:
        """
        Generate PDF from JSON data (without uploading).

        Args:
            data: JSON data dictionary
            call_metadata: Optional call metadata (date, duration, etc.)
            template_name: Jinja2 template filename

        Returns:
            PDF file as bytes

        Raises:
            PDFGeneratorError: If rendering fails
        """
        try:
            # Prepare template context
            context = self._prepare_context(data, call_metadata or {})

            # Render HTML
            template = self.jinja_env.get_template(template_name)
            html_content = template.render(**context)

            # Convert to PDF
            pdf_bytes = HTML(string=html_content).write_pdf()

            logger.debug(f"Generated PDF: {len(pdf_bytes)} bytes")

            return pdf_bytes

        except Exception as e:
            logger.error(f"PDF rendering failed: {e}", exc_info=True)
            raise PDFGeneratorError(f"Rendering failed: {e}") from e

    def _prepare_context(
        self,
        data: Dict[str, Any],
        call_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare Jinja2 context with data and formatting helpers.

        Args:
            data: Candidate JSON data
            call_metadata: Call information (date, duration, etc.)

        Returns:
            Context dictionary for template rendering
        """
        # Format call date
        started_at = call_metadata.get("started_at")
        call_date = "N/D"
        if started_at:
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            call_date = started_at.strftime("%d/%m/%Y %H:%M")

        # Format call duration
        duration_seconds = call_metadata.get("duration_seconds")
        call_duration = "N/D"
        if duration_seconds:
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            call_duration = f"{minutes}m {seconds}s"

        # Generation timestamp
        generation_date = datetime.utcnow().strftime("%d/%m/%Y %H:%M")

        # Build context
        context = {
            "data": data,
            "call_date": call_date,
            "call_duration": call_duration,
            "generation_date": generation_date,
            "call_id": call_metadata.get("id"),
        }

        return context

    async def _fetch_call_metadata(self, call_id: UUID) -> Dict[str, Any]:
        """Fetch call metadata from database."""
        db = get_database()
        call = await db.fetch_one(
            """
            SELECT id, project_id, phone_number, started_at, ended_at, duration_seconds
            FROM calls
            WHERE id = :id
            """,
            {"id": str(call_id)}
        )

        if not call:
            raise PDFGeneratorError(f"Call {call_id} not found")

        return dict(call)

    async def _fetch_project_slug(self, project_id: Optional[UUID]) -> str:
        """
        Fetch project slug from database.
        Falls back to default project if project_id is None.
        """
        db = get_database()

        if project_id:
            project = await db.fetch_one(
                "SELECT slug FROM projects WHERE id = :id",
                {"id": str(project_id)}
            )
        else:
            # Fetch default project slug from settings
            setting = await db.fetch_one(
                "SELECT value FROM settings WHERE key = 'default_project_slug'"
            )
            if setting:
                project = await db.fetch_one(
                    "SELECT slug FROM projects WHERE slug = :slug",
                    {"slug": setting["value"]}
                )
            else:
                project = None

        if not project:
            # Fallback to generic slug
            return "default"

        return project["slug"]

    async def _update_record_pdf_info(
        self,
        call_id: UUID,
        pdf_key: str
    ) -> None:
        """Update record with PDF key and generation timestamp."""
        db = get_database()
        await db.execute(
            """
            UPDATE records
            SET pdf_key = :pdf_key,
                pdf_generated_at = :generated_at
            WHERE call_id = :call_id
            """,
            {
                "call_id": str(call_id),
                "pdf_key": pdf_key,
                "generated_at": datetime.utcnow()
            }
        )

    async def download_pdf(self, call_id: UUID) -> bytes:
        """
        Download PDF for a call from S3.

        Args:
            call_id: UUID of the call

        Returns:
            PDF file bytes

        Raises:
            PDFGeneratorError: If PDF not found or download fails
        """
        db = get_database()

        # Fetch PDF key from records
        record = await db.fetch_one(
            "SELECT pdf_key FROM records WHERE call_id = :call_id",
            {"call_id": str(call_id)}
        )

        if not record or not record["pdf_key"]:
            raise PDFGeneratorError(f"No PDF found for call {call_id}")

        # Download from S3
        try:
            pdf_bytes = self.s3_client.download_pdf(record["pdf_key"])
            return pdf_bytes
        except Exception as e:
            raise PDFGeneratorError(f"Failed to download PDF: {e}") from e

    async def regenerate_pdf(self, call_id: UUID) -> str:
        """
        Regenerate PDF for an existing record.
        Useful for:
        - Fixing template errors
        - Testing new template versions
        - Updating PDFs after data corrections

        Args:
            call_id: UUID of the call

        Returns:
            S3 object key of new PDF

        Raises:
            PDFGeneratorError: If record not found or regeneration fails
        """
        db = get_database()

        # Fetch existing record
        record = await db.fetch_one(
            "SELECT json_data, pdf_key FROM records WHERE call_id = :call_id",
            {"call_id": str(call_id)}
        )

        if not record:
            raise PDFGeneratorError(f"No record found for call {call_id}")

        # Delete old PDF if exists
        if record["pdf_key"]:
            try:
                self.s3_client.delete_pdf(record["pdf_key"])
                logger.info(f"Deleted old PDF: {record['pdf_key']}")
            except Exception as e:
                logger.warning(f"Failed to delete old PDF: {e}")

        # Generate new PDF
        import json
        json_data = json.loads(record["json_data"]) if isinstance(record["json_data"], str) else record["json_data"]

        s3_key = await self.generate_and_upload_pdf(
            call_id=call_id,
            json_data=json_data
        )

        logger.info(f"PDF regenerated for call {call_id}")

        return s3_key

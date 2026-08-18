"""
Ascolta - Post Processing Service
Extracts structured JSON from call transcripts using GPT-4 (Prompt B)
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import openai
from app.config import get_settings
from app.database.db import get_database

logger = logging.getLogger(__name__)


class PostProcessingError(Exception):
    """Raised when post-processing fails."""
    pass


class PostProcessor:
    """
    Processes completed call transcripts to extract structured data.
    Uses Prompt B from the project configuration.
    """

    def __init__(self):
        self.settings = get_settings()
        self.client = openai.OpenAI(api_key=self.settings.openai_api_key)

    async def process_call(
        self,
        call_id: UUID,
        allow_processed: bool = False,
    ) -> Dict[str, Any]:
        """
        Process a completed call:
        1. Fetch call and project data
        2. Build transcript text
        3. Send to GPT-4 with Prompt B
        4. Parse and validate JSON response
        5. Store in records table
        6. Update call status to 'processed'

        Args:
            call_id: UUID of the completed call

        Returns:
            Dict containing the extracted JSON data

        Raises:
            PostProcessingError: If processing fails
        """
        db = get_database()

        try:
            logger.info(f"Starting post-processing for call {call_id}")

            # 1. Fetch call data
            call = await self._fetch_call(call_id)
            if not call:
                raise PostProcessingError(f"Call {call_id} not found")

            valid_statuses = ["completed", "consented"]
            if allow_processed:
                valid_statuses.append("processed")

            if call["status"] not in valid_statuses:
                raise PostProcessingError(
                    f"Call {call_id} has invalid status: {call['status']}"
                )

            # Update status to 'processing'
            await db.execute(
                "UPDATE calls SET status = 'processing' WHERE id = :id",
                {"id": str(call_id)}
            )

            # 2. Fetch project (for Prompt B)
            project = await self._fetch_project(call.get("project_id"))
            if not project:
                raise PostProcessingError(
                    f"Project not found for call {call_id}"
                )

            prompt_b = project["prompt_b"]

            # 3. Build transcript
            transcript_text = await self._build_transcript(call_id)
            if not transcript_text:
                raise PostProcessingError(
                    f"No transcript found for call {call_id}"
                )

            logger.info(
                f"Processing call {call_id}: {len(transcript_text)} chars transcript"
            )

            # 4. Extract JSON via GPT-4
            json_data = await self._extract_json(
                transcript_text=transcript_text,
                prompt_b=prompt_b,
                phone_number=call.get("phone_number"),
            )

            # 5. Store in records table
            record_id = await self._store_record(
                call_id=call_id,
                json_data=json_data
            )

            # 6. Update call status to 'processed'
            await db.execute(
                "UPDATE calls SET status = 'processed' WHERE id = :id",
                {"id": str(call_id)}
            )

            logger.info(
                f"Post-processing completed for call {call_id}, record {record_id}"
            )

            return json_data

        except Exception as e:
            logger.error(
                f"Post-processing failed for call {call_id}: {e}",
                exc_info=True
            )
            # Mark call as 'completed' (not 'processed') to indicate failure
            await db.execute(
                "UPDATE calls SET status = 'completed' WHERE id = :id",
                {"id": str(call_id)}
            )
            raise PostProcessingError(f"Failed to process call: {e}") from e

    async def _fetch_call(self, call_id: UUID) -> Optional[Dict[str, Any]]:
        """Fetch call data from database."""
        db = get_database()
        call = await db.fetch_one(
            """
            SELECT id, project_id, phone_number, status, started_at
            FROM calls
            WHERE id = :id
            """,
            {"id": str(call_id)}
        )
        return dict(call) if call else None

    async def _fetch_project(
        self, project_id: Optional[UUID]
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch project data.
        If project_id is None, fetch default project.
        """
        db = get_database()

        # Runs from the automatic post-call pipeline (webhook.py ->
        # call_manager -> here), triggered by the provider webhook with no
        # user request and no JWT - no request-scoped GUC has been set (see
        # auth_middleware.get_current_user_rls_scoped), so the RLS policy
        # added 18/08 on `projects` would otherwise deny this lookup for
        # every call. project_id comes from the call record itself, not
        # from anything a caller controls, so bypassing tenant filtering
        # for this one internal lookup is safe.
        async with db.transaction():
            await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
            if project_id:
                project = await db.fetch_one(
                    """
                    SELECT id, slug, prompt_b, output_config
                    FROM projects
                    WHERE id = :id AND is_active = TRUE
                    """,
                    {"id": str(project_id)}
                )
            else:
                # Fetch default project
                project = await db.fetch_one(
                    """
                    SELECT p.id, p.slug, p.prompt_b, p.output_config
                    FROM projects p
                    INNER JOIN settings s ON s.key = 'default_project_slug'
                    WHERE p.slug = s.value AND p.is_active = TRUE
                    LIMIT 1
                    """
                )

        return dict(project) if project else None

    async def _build_transcript(self, call_id: UUID) -> str:
        """
        Build full transcript text from database.
        Format: "USER: ...\nASSISTANT: ...\n"
        """
        db = get_database()
        transcripts = await db.fetch_all(
            """
            SELECT role, content, timestamp
            FROM transcripts
            WHERE call_id = :call_id
            ORDER BY timestamp ASC
            """,
            {"call_id": str(call_id)}
        )

        if not transcripts:
            return ""

        lines = []
        for t in transcripts:
            role = t["role"].upper()
            content = t["content"].strip()
            if content:
                lines.append(f"{role}: {content}")

        return "\n\n".join(lines)

    async def _extract_json(
        self,
        transcript_text: str,
        prompt_b: str,
        phone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract structured JSON from transcript using GPT-4.

        Args:
            transcript_text: Full conversation transcript
            prompt_b: Data extraction prompt from project
            phone_number: Caller's phone number (injected into context)

        Returns:
            Parsed JSON dictionary

        Raises:
            PostProcessingError: If extraction fails or JSON is invalid
        """
        try:
            # Build context with metadata
            context = f"""TRASCRIZIONE COLLOQUIO:
{transcript_text}

METADATI:
- Numero telefono: {phone_number or 'Non disponibile'}
"""

            # Call GPT-4 with Prompt B
            logger.debug(f"Calling GPT-4 for JSON extraction")

            response = self.client.chat.completions.create(
                model="gpt-4o",  # Use GPT-4 Turbo for best JSON extraction
                messages=[
                    {"role": "system", "content": prompt_b},
                    {"role": "user", "content": context}
                ],
                temperature=0.3,  # Low temp for structured output
                max_tokens=2000,
                response_format={"type": "json_object"}  # Force JSON mode
            )

            # Extract JSON from response
            raw_json = response.choices[0].message.content
            if not raw_json:
                raise PostProcessingError("GPT-4 returned empty response")

            # Parse JSON
            try:
                json_data = json.loads(raw_json)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from GPT-4: {raw_json}")
                raise PostProcessingError(f"Invalid JSON response: {e}") from e

            # Inject phone number if not present
            if phone_number and not json_data.get("phone_number"):
                json_data["phone_number"] = phone_number

            logger.debug(f"Extracted JSON with {len(json_data)} top-level fields")

            return json_data

        except openai.OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise PostProcessingError(f"OpenAI API error: {e}") from e

    async def _store_record(
        self,
        call_id: UUID,
        json_data: Dict[str, Any]
    ) -> int:
        """
        Store extracted JSON in records table.

        Args:
            call_id: UUID of the call
            json_data: Extracted JSON dictionary

        Returns:
            Record ID (serial primary key)
        """
        db = get_database()

        # Check if record already exists (idempotency)
        existing = await db.fetch_one(
            "SELECT id FROM records WHERE call_id = :call_id",
            {"call_id": str(call_id)}
        )

        if existing:
            # Update existing record
            await db.execute(
                """
                UPDATE records
                SET json_data = :json_data,
                    updated_at = :updated_at
                WHERE call_id = :call_id
                """,
                {
                    "call_id": str(call_id),
                    "json_data": json.dumps(json_data),
                    "updated_at": datetime.utcnow()
                }
            )
            record_id = existing["id"]
            logger.info(f"Updated existing record {record_id}")
        else:
            # Insert new record
            result = await db.fetch_one(
                """
                INSERT INTO records (call_id, json_data, created_at, updated_at)
                VALUES (:call_id, :json_data, :created_at, :updated_at)
                RETURNING id
                """,
                {
                    "call_id": str(call_id),
                    "json_data": json.dumps(json_data),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            )
            record_id = result["id"]
            logger.info(f"Created new record {record_id}")

        return record_id

    async def reprocess_call(self, call_id: UUID) -> Dict[str, Any]:
        """
        Reprocess a call that was already processed.
        Useful for:
        - Fixing extraction errors
        - Testing new Prompt B versions
        - Regenerating data after manual transcript edits

        Args:
            call_id: UUID of the call to reprocess

        Returns:
            Updated JSON data
        """
        logger.info(f"Reprocessing call {call_id}")
        return await self.process_call(call_id, allow_processed=True)

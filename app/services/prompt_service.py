"""
Voxlyne - Prompt Versioning Service

Manages prompt versions, activation, rollback, and diff.
"""

import difflib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from app.database.db import get_database

logger = logging.getLogger(__name__)


class PromptService:
    """
    Service for prompt version management.

    Features:
    - Create new prompt versions
    - Activate/deactivate versions
    - Rollback to previous versions
    - Generate diff between versions
    - Track version history
    """

    async def get_versions(
        self,
        project_id: UUID,
        prompt_type: str,
    ) -> List[Dict]:
        """
        Get all versions for a project's prompt type.

        Args:
            project_id: Project UUID
            prompt_type: 'A' or 'B'

        Returns:
            List of version dicts
        """
        db = get_database()

        versions = await db.fetch_all(
            """
            SELECT pv.*, u.full_name as creator_name, u.email as creator_email
            FROM prompt_versions pv
            LEFT JOIN users u ON pv.created_by = u.id
            WHERE pv.project_id = :project_id
              AND pv.prompt_type = :prompt_type
            ORDER BY pv.version DESC
            """,
            {"project_id": str(project_id), "prompt_type": prompt_type},
        )

        return [dict(v) for v in versions]

    async def get_version(
        self,
        version_id: UUID,
    ) -> Optional[Dict]:
        """
        Get a specific prompt version by ID.

        Args:
            version_id: Version UUID

        Returns:
            Version dict or None
        """
        db = get_database()

        version = await db.fetch_one(
            """
            SELECT pv.*, u.full_name as creator_name, u.email as creator_email
            FROM prompt_versions pv
            LEFT JOIN users u ON pv.created_by = u.id
            WHERE pv.id = :version_id
            """,
            {"version_id": str(version_id)},
        )

        return dict(version) if version else None

    async def get_active_version(
        self,
        project_id: UUID,
        prompt_type: str,
    ) -> Optional[Dict]:
        """
        Get the active version for a project's prompt type.

        Args:
            project_id: Project UUID
            prompt_type: 'A' or 'B'

        Returns:
            Active version dict or None
        """
        db = get_database()

        version = await db.fetch_one(
            """
            SELECT pv.*, u.full_name as creator_name
            FROM prompt_versions pv
            LEFT JOIN users u ON pv.created_by = u.id
            WHERE pv.project_id = :project_id
              AND pv.prompt_type = :prompt_type
              AND pv.is_active = TRUE
            """,
            {"project_id": str(project_id), "prompt_type": prompt_type},
        )

        return dict(version) if version else None

    async def create_version(
        self,
        project_id: UUID,
        prompt_type: str,
        content: str,
        created_by: Optional[UUID] = None,
        activate: bool = False,
    ) -> Dict:
        """
        Create a new prompt version.

        Args:
            project_id: Project UUID
            prompt_type: 'A' or 'B'
            content: Prompt content
            created_by: User UUID who created the version
            activate: Whether to activate immediately

        Returns:
            Created version dict
        """
        db = get_database()

        # Get next version number
        result = await db.fetch_one(
            "SELECT get_next_prompt_version(:project_id, :prompt_type) as next_version",
            {"project_id": str(project_id), "prompt_type": prompt_type},
        )
        next_version = result["next_version"]

        # Insert new version
        version = await db.fetch_one(
            """
            INSERT INTO prompt_versions (project_id, prompt_type, version, content, created_by, is_active)
            VALUES (:project_id, :prompt_type, :version, :content, :created_by, :is_active)
            RETURNING *
            """,
            {
                "project_id": str(project_id),
                "prompt_type": prompt_type,
                "version": next_version,
                "content": content,
                "created_by": str(created_by) if created_by else None,
                "is_active": activate,
            },
        )

        # Log history
        await self._log_history(
            version_id=UUID(str(version["id"])),
            action="created",
            performed_by=created_by,
        )

        # If activating, deactivate others
        if activate:
            await self._deactivate_others(
                project_id=project_id,
                prompt_type=prompt_type,
                except_version_id=UUID(str(version["id"])),
            )
            await self._log_history(
                version_id=UUID(str(version["id"])),
                action="activated",
                performed_by=created_by,
            )

        logger.info(f"Created prompt version {next_version} for project {project_id}")

        return dict(version)

    async def activate_version(
        self,
        version_id: UUID,
        performed_by: Optional[UUID] = None,
    ) -> bool:
        """
        Activate a prompt version.

        Args:
            version_id: Version UUID to activate
            performed_by: User UUID performing the action

        Returns:
            True if successful
        """
        db = get_database()

        # Get version details
        version = await self.get_version(version_id)
        if not version:
            return False

        # Use database function
        result = await db.fetch_one(
            "SELECT activate_prompt_version(:version_id, :user_id) as success",
            {
                "version_id": str(version_id),
                "user_id": str(performed_by) if performed_by else None,
            },
        )

        if result and result["success"]:
            # Also update the project's prompt_a or prompt_b
            field = "prompt_a" if version["prompt_type"] == "A" else "prompt_b"
            await db.execute(
                f"UPDATE projects SET {field} = :content, updated_at = :updated_at WHERE id = :project_id",
                {
                    "content": version["content"],
                    "updated_at": datetime.now(timezone.utc),
                    "project_id": str(version["project_id"]),
                },
            )

            logger.info(f"Activated prompt version {version_id}")
            return True

        return False

    async def rollback_to_version(
        self,
        version_id: UUID,
        performed_by: Optional[UUID] = None,
    ) -> Optional[Dict]:
        """
        Rollback to a specific version by creating a new version with its content.

        Args:
            version_id: Version UUID to rollback to
            performed_by: User UUID performing the action

        Returns:
            New version dict or None
        """
        db = get_database()

        # Get source version
        source = await self.get_version(version_id)
        if not source:
            return None

        # Create new version with same content
        new_version = await self.create_version(
            project_id=UUID(str(source["project_id"])),
            prompt_type=source["prompt_type"],
            content=source["content"],
            created_by=performed_by,
            activate=True,
        )

        # Log rollback
        await self._log_history(
            version_id=UUID(str(new_version["id"])),
            action="rollback",
            performed_by=performed_by,
            metadata={"source_version_id": str(version_id), "source_version": source["version"]},
        )

        logger.info(f"Rolled back to version {version_id}, created new version {new_version['version']}")

        return new_version

    async def get_diff(
        self,
        version_id_a: UUID,
        version_id_b: UUID,
    ) -> Dict:
        """
        Generate diff between two prompt versions.

        Args:
            version_id_a: First version UUID (older)
            version_id_b: Second version UUID (newer)

        Returns:
            Dict with diff details
        """
        version_a = await self.get_version(version_id_a)
        version_b = await self.get_version(version_id_b)

        if not version_a or not version_b:
            raise ValueError("One or both versions not found")

        # Generate unified diff
        lines_a = version_a["content"].splitlines(keepends=True)
        lines_b = version_b["content"].splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=f"Version {version_a['version']}",
            tofile=f"Version {version_b['version']}",
            lineterm="",
        ))

        # Count additions and deletions
        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return {
            "version_a": version_a,
            "version_b": version_b,
            "diff": diff,
            "additions": additions,
            "deletions": deletions,
        }

    async def get_history(
        self,
        version_id: UUID,
    ) -> List[Dict]:
        """
        Get history for a specific version.

        Args:
            version_id: Version UUID

        Returns:
            List of history entries
        """
        db = get_database()

        history = await db.fetch_all(
            """
            SELECT pvh.*, u.full_name as performer_name, u.email as performer_email
            FROM prompt_version_history pvh
            LEFT JOIN users u ON pvh.performed_by = u.id
            WHERE pvh.prompt_version_id = :version_id
            ORDER BY pvh.created_at DESC
            """,
            {"version_id": str(version_id)},
        )

        return [dict(h) for h in history]

    async def _deactivate_others(
        self,
        project_id: UUID,
        prompt_type: str,
        except_version_id: UUID,
    ) -> None:
        """Deactivate all versions except the specified one."""
        db = get_database()

        await db.execute(
            """
            UPDATE prompt_versions
            SET is_active = FALSE
            WHERE project_id = :project_id
              AND prompt_type = :prompt_type
              AND id != :except_id
              AND is_active = TRUE
            """,
            {
                "project_id": str(project_id),
                "prompt_type": prompt_type,
                "except_id": str(except_version_id),
            },
        )

    async def _log_history(
        self,
        version_id: UUID,
        action: str,
        performed_by: Optional[UUID] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Log an action to version history."""
        db = get_database()

        await db.execute(
            """
            INSERT INTO prompt_version_history (prompt_version_id, action, performed_by, metadata)
            VALUES (:version_id, :action, :performed_by, :metadata)
            """,
            {
                "version_id": str(version_id),
                "action": action,
                "performed_by": str(performed_by) if performed_by else None,
                "metadata": metadata or {},
            },
        )


# Singleton instance
_prompt_service = None


def get_prompt_service() -> PromptService:
    """Get the prompt service singleton."""
    global _prompt_service
    if _prompt_service is None:
        _prompt_service = PromptService()
    return _prompt_service

"""
Voxlyne - CRM Data Mapper

Flexible data mapping from interview JSON to CRM field formats.
Supports JSONPath-like expressions and transformations.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DataMapper:
    """
    Maps interview JSON data to CRM field formats.

    Supports:
    - JSONPath-like expressions: $.field.subfield, $.array[0]
    - Static values: 'static value'
    - Transforms: $.field | transform_name
    """

    # Default HubSpot field mapping
    HUBSPOT_DEFAULTS: Dict[str, str] = {
        # Standard HubSpot properties
        "email": "$.email",
        "firstname": "$.candidate_name | first_name",
        "lastname": "$.candidate_name | last_name",
        "phone": "$.phone_number",
        "jobtitle": "$.role_targets[0]",
        "company": "'Candidato Voxlyne'",
        "hs_lead_status": "'NEW'",

        # Custom properties (will be created if they don't exist)
        "voxlyne_experience_summary": "$.experience_summary",
        "voxlyne_seniority": "$.seniority_estimate",
        "voxlyne_hard_skills": "$.hard_skills | join",
        "voxlyne_soft_skills": "$.soft_skills | join",
        "voxlyne_availability_relocate": "$.availability.willing_to_relocate | bool_to_str",
        "voxlyne_availability_travel": "$.availability.willing_to_travel | bool_to_str",
        "voxlyne_start_date": "$.availability.start_date_estimate",
        "voxlyne_motivations": "$.motivations",
        "voxlyne_fit_score": "$.overall_fit_score | to_str",
        "voxlyne_recruiter_notes": "$.recruiter_notes",
        "voxlyne_call_id": "$._call_metadata.id",
        "voxlyne_call_date": "$._call_metadata.started_at | date",
        "voxlyne_call_duration": "$._call_metadata.duration_seconds | duration",
    }

    # Generic webhook mapping (sends most data as-is)
    WEBHOOK_DEFAULTS: Dict[str, str] = {
        "candidate_name": "$.candidate_name",
        "phone_number": "$.phone_number",
        "email": "$.email",
        "role_targets": "$.role_targets",
        "seniority_estimate": "$.seniority_estimate",
        "experience_summary": "$.experience_summary",
        "hard_skills": "$.hard_skills",
        "soft_skills": "$.soft_skills",
        "availability": "$.availability",
        "motivations": "$.motivations",
        "overall_fit_score": "$.overall_fit_score",
        "recruiter_notes": "$.recruiter_notes",
        "call_id": "$._call_metadata.id",
        "call_started_at": "$._call_metadata.started_at",
        "call_duration_seconds": "$._call_metadata.duration_seconds",
    }

    def map_to_crm(
        self,
        json_data: Dict[str, Any],
        call_metadata: Dict[str, Any],
        field_mapping: Optional[Dict[str, str]] = None,
        provider: str = "hubspot",
    ) -> Dict[str, Any]:
        """
        Map interview data to CRM format.

        Args:
            json_data: Extracted candidate JSON from GPT-4
            call_metadata: Call info (id, started_at, duration_seconds)
            field_mapping: Custom field mapping from project config
            provider: CRM provider name

        Returns:
            Mapped data ready for CRM API
        """
        # Get default mapping for provider
        if provider == "hubspot":
            defaults = self.HUBSPOT_DEFAULTS.copy()
        elif provider == "generic_webhook":
            defaults = self.WEBHOOK_DEFAULTS.copy()
        else:
            defaults = {}

        # Merge with custom mapping (custom overrides defaults)
        effective_mapping = {**defaults, **(field_mapping or {})}

        # Add call metadata to source data
        source_data = {
            **json_data,
            "_call_metadata": call_metadata,
        }

        # Map each field
        result: Dict[str, Any] = {}
        for crm_field, expression in effective_mapping.items():
            try:
                value = self._evaluate_expression(expression, source_data)
                if value is not None and value != "":
                    result[crm_field] = value
            except Exception as e:
                logger.warning(f"Error mapping field {crm_field}: {e}")
                continue

        return result

    def _evaluate_expression(
        self,
        expression: str,
        data: Dict[str, Any],
    ) -> Optional[Any]:
        """
        Evaluate a JSONPath-like expression.

        Supports:
        - $.field.subfield - Nested field access
        - $.array[0] - Array index
        - 'static value' - Static string
        - $.field | transform - Apply transformation
        """
        expression = expression.strip()

        # Static value (single quotes)
        if expression.startswith("'") and expression.endswith("'"):
            return expression[1:-1]

        # JSONPath with optional transform
        if "|" in expression:
            path, transform = expression.split("|", 1)
            value = self._get_path_value(path.strip(), data)
            return self._apply_transform(value, transform.strip())

        return self._get_path_value(expression, data)

    def _get_path_value(
        self,
        path: str,
        data: Dict[str, Any],
    ) -> Optional[Any]:
        """Extract value from nested dict using JSONPath-like syntax."""
        if not path.startswith("$."):
            return None

        path = path[2:]  # Remove "$."
        if not path:
            return data

        current: Any = data

        for part in self._split_path(path):
            if current is None:
                return None

            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx] if 0 <= idx < len(current) else None
                except (ValueError, IndexError):
                    return None
            else:
                return None

        return current

    def _split_path(self, path: str) -> List[str]:
        """Split path into parts, handling array indices."""
        parts: List[str] = []
        for segment in path.split("."):
            # Handle array[0] notation
            match = re.match(r"(\w+)\[(\d+)\]", segment)
            if match:
                parts.append(match.group(1))
                parts.append(match.group(2))
            else:
                parts.append(segment)
        return parts

    def _apply_transform(
        self,
        value: Any,
        transform: str,
    ) -> Optional[Any]:
        """Apply transformation to value."""
        if value is None:
            return None

        transform = transform.lower()

        # Name transformations
        if transform == "first_name":
            if isinstance(value, str):
                parts = value.strip().split()
                return parts[0] if parts else None
            return None

        elif transform == "last_name":
            if isinstance(value, str):
                parts = value.strip().split()
                return " ".join(parts[1:]) if len(parts) > 1 else ""
            return None

        # Array join
        elif transform == "join" or transform.startswith("join("):
            separator = ", "
            # Extract custom separator: join('; ')
            match = re.match(r"join\(['\"](.*)['\"]\)", transform)
            if match:
                separator = match.group(1)
            if isinstance(value, list):
                return separator.join(str(v) for v in value if v)
            return str(value) if value else None

        # Boolean to string
        elif transform == "bool_to_str":
            if isinstance(value, bool):
                return "Sì" if value else "No"
            return str(value) if value else None

        # To string
        elif transform == "to_str":
            return str(value) if value is not None else None

        # Date formatting
        elif transform == "date":
            if value:
                try:
                    from datetime import datetime
                    if isinstance(value, datetime):
                        return value.strftime("%d/%m/%Y %H:%M")
                    elif isinstance(value, str):
                        # Try to parse ISO format
                        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        return dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    return str(value)
            return None

        # Duration formatting (seconds to human-readable)
        elif transform == "duration":
            try:
                seconds = int(value)
                minutes = seconds // 60
                secs = seconds % 60
                return f"{minutes}m {secs}s"
            except (ValueError, TypeError):
                return str(value) if value else None

        # Unknown transform - return as-is
        logger.warning(f"Unknown transform: {transform}")
        return value

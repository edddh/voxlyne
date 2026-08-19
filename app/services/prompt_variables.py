"""
Ascolta - {{key}} custom prompt variable substitution.

maintainer, 20/08: "nei prompt ... ci sono dei tag che andrebbero collegati
a dei campi o attivi (come data e ora) oppure custom". Two kinds of
{{tag}}, distinguished by naming convention, not storage:

- {{system__xxx}} (e.g. {{system__caller_id}}) - resolved by the voice
  PROVIDER itself at call time (confirmed: ElevenLabs' and xAI's
  realtime APIs both understand this convention natively - see
  runtime_workers/provision_elevenlabs.py and the working, live-call-
  verified Comune/URP template prompt, which sends {{system__caller_id}}
  through unchanged and xAI resolves it). Ascolta must NEVER substitute
  these - hence the exclusion below.
- {{anything_else}} - a per-project custom variable Ascolta itself
  substitutes, from projects.custom_variables (see db_migrations/
  versions/e5e14da0c6e3_*).
"""

import re
from typing import Any, Dict, Optional

# {{key}} - word chars/underscore/hyphen only, no spaces, so this never
# accidentally matches literal double-brace text that isn't meant as a
# tag (e.g. JSON examples embedded in a prompt).
TAG_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_-]+)\s*\}\}")


def extract_tags(text: Optional[str]) -> list[str]:
    """All {{key}} tags found in text, in first-seen order, deduplicated."""
    if not text:
        return []
    seen: list[str] = []
    for match in TAG_PATTERN.finditer(text):
        key = match.group(1)
        if key not in seen:
            seen.append(key)
    return seen


def extract_custom_tags(text: Optional[str]) -> list[str]:
    """extract_tags(), minus any system__-prefixed tag."""
    return [key for key in extract_tags(text) if not key.startswith("system__")]


def substitute_custom_variables(text: Optional[str], values: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Replace every {{key}} in text with str(values[key]), except
    {{system__xxx}} tags (left untouched for the voice provider to
    resolve) and any {{key}} with no matching value (left as-is,
    visibly unresolved, rather than silently blanked - an admin who
    forgot to fill in a custom variable should see the literal {{tag}}
    in a test call, not a sentence with a silent hole in it).
    """
    if not text:
        return text
    values = values or {}

    def _replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key.startswith("system__"):
            return match.group(0)
        if key in values and values[key] is not None:
            return str(values[key])
        return match.group(0)

    return TAG_PATTERN.sub(_replace, text)

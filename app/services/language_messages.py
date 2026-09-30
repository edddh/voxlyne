"""Normalize short voice-agent messages before provider provisioning."""

from __future__ import annotations

def resolve_first_message(message: str | None, language: str | None) -> str:
    """Keep the project-defined greeting without provider-specific overrides."""
    del language
    return (message or "").strip()

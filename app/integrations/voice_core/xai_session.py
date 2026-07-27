from __future__ import annotations

from typing import Any


def build_xai_accept_payload(*, model: str, voice: str, input_format: str, output_format: str, language: str, instructions: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "output_modalities": ["audio"],
        "tool_choice": "auto",
        "tools": tools,
        "audio": {
            "input": {
                "format": {"type": input_format},
                "transcription": {"model": "whisper-1", "language": language or "it"},
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": True,
                    "interrupt_response": True,
                    "threshold": 0.97,
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": 350,
                    "idle_timeout_ms": 12000,
                },
            },
            "output": {
                "format": {"type": output_format},
                "voice": voice,
                "speed": 1.0,
            },
        },
    }


def build_xai_session_update(
    *,
    voice: str,
    language: str,
    instructions: str,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "realtime",
        "instructions": instructions,
        "output_modalities": ["audio"],
        "tools": tools,
        "tool_choice": "auto",
        "voice": voice,
        "turn_detection": {
            "type": "server_vad",
            "create_response": True,
            "interrupt_response": True,
            "threshold": 0.97,
            "prefix_padding_ms": 500,
            "silence_duration_ms": 350,
            "idle_timeout_ms": 12000,
        },
        "audio": {
            "input": {
                "transcription": {
                    "language_hint": language or "it",
                },
            },
        },
    }

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class VoiceCallState:
    call_id: str
    scenario_name: str = ""
    caller_number: str = ""
    instructions: str = ""
    first_message: str = ""
    response_language: str = "en"
    provider: str = "openai"
    model: str = ""
    voice: str = ""
    api_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class VoiceStateStore:
    def __init__(self) -> None:
        self._states: dict[str, VoiceCallState] = {}

    def put(self, state: VoiceCallState) -> None:
        self._states[state.call_id] = state

    def get(self, call_id: str, default: Any = None) -> Any:
        return self._states.get(call_id, default)

    def pop(self, call_id: str, default: Any = None) -> Any:
        return self._states.pop(call_id, default)

    def __contains__(self, call_id: object) -> bool:
        return call_id in self._states

    def __getitem__(self, call_id: str) -> VoiceCallState:
        return self._states[call_id]

    def __setitem__(self, call_id: str, state: dict[str, Any] | VoiceCallState) -> None:
        if isinstance(state, VoiceCallState):
            self._states[call_id] = state
            return
        normalized = dict(state)
        if "scenario" in normalized and "scenario_name" not in normalized:
            normalized["scenario_name"] = normalized.pop("scenario")
        if "prompt_variant" in normalized and "scenario_name" not in normalized:
            normalized["scenario_name"] = normalized.pop("prompt_variant")
        self._states[call_id] = VoiceCallState(call_id=call_id, **normalized)

    def __iter__(self) -> Iterator[str]:
        return iter(self._states)

    def clear(self) -> None:
        self._states.clear()

    def as_dict(self, call_id: str) -> dict[str, Any] | None:
        state = self._states.get(call_id)
        if state is None:
            return None
        return {
            "call_id": state.call_id,
            "scenario_name": state.scenario_name,
            "caller_number": state.caller_number,
            "instructions": state.instructions,
            "first_message": state.first_message,
            "response_language": state.response_language,
            "provider": state.provider,
            "model": state.model,
            "voice": state.voice,
            "metadata": dict(state.metadata),
        }

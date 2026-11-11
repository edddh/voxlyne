import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(
    os.environ.get("VOXLYNE_CONFIG_PATH")
    or (
        (Path.cwd() / "voxlyne-stack-config.json")
        if Path.cwd().name == ROOT.name
        else ROOT / "voxlyne-stack-config.json"
    )
)
def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {}


def _read_json_from_env() -> dict[str, Any]:
    raw = os.environ.get("VOXLYNE_CONFIG_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_config() -> dict[str, Any]:
    env_config = _read_json_from_env()
    if env_config:
        return env_config
    return _read_json(CONFIG_PATH)

def load_scenario_config(path: str | None) -> dict[str, Any]:
    cfg = load_config()
    scenario_context = cfg.get("scenario_context")
    if isinstance(scenario_context, dict):
        return scenario_context
    return {}

def load_realtime_config(cfg: dict[str, Any]) -> dict[str, Any]:
    realtime_cfg = cfg.get("realtime") if isinstance(cfg.get("realtime"), dict) else {}
    if realtime_cfg:
        return realtime_cfg
    openai_cfg = cfg.get("openai") if isinstance(cfg.get("openai"), dict) else {}
    return openai_cfg if isinstance(openai_cfg, dict) else {}

def active_services(cfg: dict[str, Any]) -> set[str]:
    services = cfg.get("services")
    if isinstance(services, list):
        return {str(s).lower() for s in services}
    service = cfg.get("service")
    if isinstance(service, str):
        return {service.lower()}
    return set()


def resolve_scenario(cfg: dict[str, Any], service: str) -> dict[str, Any]:
    service_cfg = cfg.get(service) if isinstance(cfg.get(service), dict) else {}
    if not service_cfg:
        for fallback_service in ("realtime", "openai"):
            fallback_cfg = cfg.get(fallback_service) if isinstance(cfg.get(fallback_service), dict) else {}
            if fallback_cfg:
                service_cfg = fallback_cfg
                break
    response_cfg = cfg.get("response") if isinstance(cfg.get("response"), dict) else {}
    scenario_name = service_cfg.get("scenario") or cfg.get("scenario") or "tenant_runtime"
    return {
        "name": scenario_name,
        "prompt_path": None,
        "first_message": response_cfg.get("first_message"),
        "config_path": None,
    }

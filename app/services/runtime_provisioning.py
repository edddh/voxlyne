"""
Ascolta - Runtime Instance Provisioning

Generates a standalone, earlier-prototype-equivalent runtime instance for a project:
one config file + one env file + one start script + one systemd unit,
exactly mirroring how earlier-prototype.service runs (one process per scenario), but
sourcing credentials from the project/tenant's CredentialsManager instead
of a hand-edited .env file.

This deliberately does NOT attempt dynamic multi-tenant call dispatch in a
single shared process - that has no equivalent in earlier-prototype either. Each
project gets its own systemd unit, listening on its own port, exactly like
earlier-prototype.service / ascolta-runtime.service today.
"""

import json
import logging
import stat
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from app.services.credentials.manager import CredentialsManager

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTANCES_DIR = REPO_ROOT / "runtime-instances"

# engine_type -> (script relative to repo root, voice_entrypoint)
ENGINE_SCRIPTS = {
    "xai_sip_direct": ("runtime_workers/realtime_service.py", "script"),
    "openai_sip_direct": ("runtime_workers/realtime_service.py", "script"),
    "livekit_xai": ("runtime_workers/livekit_agent.py", "worker"),
    "livekit_openai": ("runtime_workers/livekit_agent.py", "worker"),
}

BASE_PORT = 3390


class RuntimeProvisioningError(Exception):
    pass


def _default_first_message(language: str) -> str:
    defaults = {
        "it": "Salve, come posso aiutarla?",
        "en": "Hello, how can I help you?",
        "es": "Hola, ¿en qué puedo ayudarle?",
        "fr": "Bonjour, comment puis-je vous aider ?",
        "de": "Guten Tag, wie kann ich Ihnen helfen?",
    }
    return defaults.get(language, defaults["it"])


def _next_free_port() -> int:
    used = set()
    if INSTANCES_DIR.exists():
        for inst_dir in INSTANCES_DIR.iterdir():
            cfg_path = inst_dir / "config.json"
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text())
                    port = cfg.get("runtime", {}).get("realtime_port")
                    if isinstance(port, int):
                        used.add(port)
                except Exception:
                    pass
    port = BASE_PORT
    while port in used:
        port += 1
    return port


async def provision_project_runtime(project: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build (and write to disk) a standalone runtime instance for a project.

    Args:
        project: dict with at least id, slug, tenant_id, voice_engine,
                 prompt_a, consent_message, language, output_config.

    Returns:
        dict with config_path, env_path, start_script_path, systemd_unit
        (text, not installed - the caller has no root), install_commands.
    """
    engine_type = project.get("voice_engine") or "openai_realtime"
    if engine_type not in ENGINE_SCRIPTS:
        raise RuntimeProvisioningError(
            f"Voice engine '{engine_type}' non ha ancora un runtime standalone "
            "generabile (supportati: " + ", ".join(ENGINE_SCRIPTS.keys()) + ")."
        )

    script_rel, voice_entrypoint = ENGINE_SCRIPTS[engine_type]
    slug = project["slug"]
    # Defensive, on top of the caller excluding templates from the
    # Projects list (app/routers/api.py::list_projects, 20/08) - a
    # template row has tenant_id=NULL, and UUID(str(None)) raised an
    # unhandled "badly formed hexadecimal UUID string" (500) instead of
    # this clear, expected error before that list-query fix existed.
    if not project.get("tenant_id"):
        raise RuntimeProvisioningError(
            "Questo progetto non ha un tenant proprietario (probabile template, non un progetto reale) - "
            "impossibile generare un'istanza runtime."
        )
    tenant_id = UUID(str(project["tenant_id"]))
    project_id = UUID(str(project["id"]))

    creds_mgr = CredentialsManager()

    env: Dict[str, str] = {}
    scenario_tools = {
        "calcom": False,
        "nextcloud": False,
        "calendar": False,
        "tasks": False,
        "files": False,
        "contacts": False,
    }

    if engine_type in ("xai_sip_direct", "livekit_xai"):
        xai_creds = await creds_mgr.get_credentials_with_fallback(
            tenant_id, project_id, "voice", "xai"
        )
        if not xai_creds.get("api_key"):
            raise RuntimeProvisioningError(
                "Nessuna credenziale xAI configurata per questo progetto/tenant "
                "(Tenant > Credenziali > voice/xai)."
            )
        env["XAI_API_KEY"] = xai_creds["api_key"]
        if xai_creds.get("webhook_secret"):
            env["XAI_WEBHOOK_SECRET"] = xai_creds["webhook_secret"]

    if engine_type in ("openai_sip_direct", "livekit_openai"):
        openai_creds = await creds_mgr.get_credentials_with_fallback(
            tenant_id, project_id, "voice", "openai_realtime"
        )
        if not openai_creds.get("api_key"):
            raise RuntimeProvisioningError(
                "Nessuna credenziale OpenAI configurata per questo progetto/tenant."
            )
        env["OPENAI_API_KEY"] = openai_creds["api_key"]

    if engine_type in ("livekit_xai", "livekit_openai"):
        lk_creds = await creds_mgr.get_credentials_with_fallback(
            tenant_id, project_id, "telephony", "livekit"
        )
        if not (lk_creds.get("url") and lk_creds.get("api_key") and lk_creds.get("api_secret")):
            raise RuntimeProvisioningError(
                "Credenziali LiveKit incomplete per questo progetto/tenant "
                "(servono url, api_key, api_secret)."
            )
        env["LIVEKIT_URL"] = lk_creds["url"]
        env["LIVEKIT_API_KEY"] = lk_creds["api_key"]
        env["LIVEKIT_API_SECRET"] = lk_creds["api_secret"]

    # Cal.com is optional - only wired if credentials exist
    calcom_creds = await creds_mgr.get_credentials_with_fallback(
        tenant_id, project_id, "calendar", "calcom"
    )
    calcom_cfg = {}
    if calcom_creds.get("api_key"):
        env["CALCOM_API_KEY"] = calcom_creds["api_key"]
        scenario_tools["calcom"] = True
        output_config = project.get("output_config") or {}
        if isinstance(output_config, str):
            try:
                output_config = json.loads(output_config)
            except json.JSONDecodeError:
                output_config = {}
        calendar_cfg = output_config.get("calendar") or {}
        calcom_cfg = {
            "base_url": "https://api.cal.com/v2",
            "event_type_id": str(calendar_cfg.get("event_type_id") or ""),
        }

    language = project.get("language") or "it"
    first_message = project.get("consent_message") or _default_first_message(language)
    primary_prompt = project["prompt_a"]

    provider = "xai" if engine_type in ("xai_sip_direct", "livekit_xai") else "openai"

    config: Dict[str, Any] = {
        "services": ["realtime"] if voice_entrypoint == "script" else ["livekit"],
        "scenario": slug,
        "response": {"language": language, "tone": "professionale", "voice_id": ""},
        "realtime": {
            "scenario": slug,
            "provider": provider,
            "model": "grok-voice-think-fast-1.0" if provider == "xai" else "gpt-realtime",
            "voice": project.get("voice_name") or ("Eve" if provider == "xai" else "marin"),
            "input_format": "audio/pcma",
            "output_format": "audio/pcma",
            "base_url": "https://api.x.ai/v1" if provider == "xai" else None,
            "websocket_base_url": "wss://api.x.ai/v1/realtime" if provider == "xai" else None,
        },
        "calcom": calcom_cfg,
        "call_settings": {"caller_id_enabled": True, "max_availability_options": 2},
        "runtime": {
            "realtime_host": "0.0.0.0",
            "realtime_port": _next_free_port(),
            "realtime_script": script_rel,
            "openai_script": script_rel,
            "voice_entrypoint": voice_entrypoint,
        },
        "voice_architecture": "new",
        "prompt_overrides": {
            "primary_prompt": primary_prompt,
            "secondary_prompt": first_message,
        },
        "scenario_context": {
            "tools": scenario_tools,
        },
    }

    instance_dir = INSTANCES_DIR / slug
    instance_dir.mkdir(parents=True, exist_ok=True)

    config_path = instance_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")

    env_lines = [
        f"# Ascolta runtime env - project {slug} (generated, do not edit manually)",
        f"ASCOLTA_CONFIG_PATH={config_path}",
        f"ASCOLTA_LIVEKIT_AGENT_NAME=ascolta-{slug}",
    ]
    for k, v in env.items():
        env_lines.append(f"{k}={v}")
    env_path = instance_dir / "runtime.env"
    env_path.write_text("\n".join(env_lines) + "\n")
    env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600

    script_full = REPO_ROOT / script_rel
    exec_line = f"{script_full} start" if voice_entrypoint == "worker" else str(script_full)
    start_script = f"""#!/bin/bash
set -euo pipefail
set -a
. "{env_path}"
set +a
unset PYTHONHOME
unset PYTHONPATH
cd "{REPO_ROOT}"
exec "{REPO_ROOT}/.venv/bin/python" {exec_line}
"""
    start_script_path = instance_dir / "start.sh"
    start_script_path.write_text(start_script)
    start_script_path.chmod(0o755)

    service_name = f"ascolta-{slug}.service"
    systemd_unit = f"""[Unit]
Description=Ascolta voice runtime ({slug})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=maintainer
Group=maintainer
WorkingDirectory={REPO_ROOT}
ExecStart={start_script_path}
Restart=always
RestartSec=5
TimeoutStopSec=20
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
"""
    unit_path = instance_dir / f"{service_name}"
    unit_path.write_text(systemd_unit)

    install_commands = [
        f"sudo cp {unit_path} /etc/systemd/system/{service_name}",
        "sudo systemctl daemon-reload",
        f"sudo systemctl enable --now {service_name}",
        f"sudo systemctl status {service_name} --no-pager",
    ]

    logger.info(f"Provisioned runtime instance for project {slug} at {instance_dir}")

    return {
        "project_slug": slug,
        "engine_type": engine_type,
        "port": config["runtime"]["realtime_port"],
        "config_path": str(config_path),
        "env_path": str(env_path),
        "start_script_path": str(start_script_path),
        "systemd_unit_path": str(unit_path),
        "systemd_unit": systemd_unit,
        "service_name": service_name,
        "install_commands": install_commands,
    }

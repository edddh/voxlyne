from typing import Any


def _resolve_tool_flags(scenario_config: dict | None) -> dict[str, bool]:
    tools_cfg = scenario_config.get("tools") if isinstance(scenario_config, dict) else {}
    if not isinstance(tools_cfg, dict):
        tools_cfg = {}

    def flag(name: str, default: bool) -> bool:
        value = tools_cfg.get(name)
        if value is None:
            return default
        return bool(value)

    nextcloud_flag = tools_cfg.get("nextcloud")
    nextcloud_enabled = True if nextcloud_flag is None else bool(nextcloud_flag)

    calendar_enabled = flag("calendar", True)
    tasks_enabled = flag("tasks", True)
    files_enabled = flag("files", True)
    contacts_enabled = flag("contacts", True)

    if nextcloud_enabled is False:
        if "calendar" not in tools_cfg:
            calendar_enabled = False
        if "tasks" not in tools_cfg:
            tasks_enabled = False
        if "files" not in tools_cfg:
            files_enabled = False
        if "contacts" not in tools_cfg:
            contacts_enabled = False
    elif nextcloud_enabled is True:
        calendar_enabled = flag("calendar", calendar_enabled)
        tasks_enabled = flag("tasks", tasks_enabled)
        files_enabled = flag("files", files_enabled)
        contacts_enabled = flag("contacts", contacts_enabled)

    return {
        "datetime": True,
        "calcom": flag("calcom", True),
        "calendar": calendar_enabled,
        "tasks": tasks_enabled,
        "files": files_enabled,
        "contacts": contacts_enabled,
    }


def build_tools(scenario_config: dict | None = None) -> list[dict[str, Any]]:
    enabled = _resolve_tool_flags(scenario_config)
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "name": "current_datetime",
            "description": "Return the current date and time in Europe/Rome, including the correct weekday. Use this before reasoning about today, tomorrow, next week, or weekday/date combinations.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            # RAG knowledge base (18/08, app/services/rag/) - not gated by
            # _resolve_tool_flags like the others below: always offered,
            # harmless if the answering project has no indexed kb_sources
            # yet (search_knowledge_base() just returns no results, see
            # call_tool() in runtime_workers/realtime_service.py).
            "type": "function",
            "name": "search_knowledge_base",
            "description": "Search this organization's knowledge base (documents and crawled web pages configured by the admin) for information relevant to the caller's question - e.g. office hours, procedures, local regulations, services offered. Use this before saying you don't know something the organization may have documented.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The question or topic to search for, in the caller's own words"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            # 20/08 (maintainer): "Rifiutata" per il Comune deve scattare se
            # il chiamante chiede esplicitamente un operatore umano - non
            # gestito, non gated come gli altri sotto: sempre offerto,
            # nessuna configurazione esterna richiesta. Il gestore
            # (runtime_workers/realtime_service.py::call_tool) segna la
            # chiamata per la finalizzazione (_finalize_call_record) e, se
            # il progetto ha un numero configurato
            # (output_config.transfer.human_operator_number), tenta un
            # trasferimento SIP reale via xAI refer API. Se non c'e' un
            # numero configurato (o il trasferimento fallisce), non esiste
            # un trasferimento reale e il modello deve congedarsi e
            # chiudere la chiamata da solo - per questo la descrizione
            # sotto non deve MAI dire "non posso trasferire": e' vero solo
            # a volte, e il modello lo diceva anche quando il trasferimento
            # stava davvero avvenendo (bug trovato il 19/08 nel primo test
            # reale con maintainer).
            "type": "function",
            "name": "request_human_operator",
            "description": "Call this the moment the caller explicitly asks to speak with a human operator/person instead of the AI assistant, or clearly states the AI cannot help them. Immediately after calling it, say a short single sentence like 'Un attimo, la metto in contatto' and then stop talking - do not say goodbye and do not claim you cannot transfer the call: the transfer may be happening right now. If the caller is still talking to you after that, the transfer was not possible - only then tell them a human will follow up later and say goodbye.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calcom_get_availability",
            "description": "Check available booking slots from Cal.com for a time range. Use this first for standard visit availability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                    "to": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                    "event_type_id": {"type": "string", "description": "Optional Cal.com event type identifier"},
                    "appointment_type": {"type": "string", "description": "Use 'standard' for a normal visit and 'sport' for sport/agonistic certificates"},
                },
                "required": ["from", "to"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calcom_book_appointment",
            "description": "Create a booking in Cal.com when a patient agrees on a valid slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "event_type_id": {"type": "string"},
                    "appointment_type": {"type": "string", "description": "Use 'standard' for a normal visit and 'sport' for sport/agonistic certificates"},
                    "execution_message": {"type": "string", "description": "Short reason for visit, max 15 words"},
                    "notes": {"type": "string", "description": "Detailed summary for booking notes"},
                    "caller_phone": {"type": "string", "description": "Phone number injected from caller ID when available"},
                    "phone": {"type": "string", "description": "Phone number for confirmation when available"},
                },
                "required": ["start", "name"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calcom_list_bookings",
            "description": "List matching Cal.com bookings to identify an existing appointment before rescheduling or cancelling it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attendee_name": {"type": "string"},
                    "caller_phone": {"type": "string", "description": "Phone number injected from caller ID when available"},
                    "phone": {"type": "string", "description": "Patient phone number when already available from caller id or provided explicitly"},
                    "reason_hint": {"type": "string", "description": "Optional reason or keyword to match against booking notes or execution message"},
                    "status": {"type": "string", "description": "Comma-separated statuses such as upcoming,past,cancelled"},
                    "from": {"type": "string", "description": "Optional ISO 8601 datetime lower bound"},
                    "to": {"type": "string", "description": "Optional ISO 8601 datetime upper bound"},
                    "event_type_id": {"type": "string"},
                    "appointment_type": {"type": "string", "description": "Use 'standard' or 'sport' when searching a specific booking type"},
                    "booking_uid": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calcom_reschedule_booking",
            "description": "Reschedule an existing Cal.com booking by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {"type": "string"},
                    "start": {"type": "string", "description": "New ISO 8601 datetime with timezone offset"},
                    "rescheduling_reason": {"type": "string"},
                },
                "required": ["booking_uid", "start"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calcom_cancel_booking",
            "description": "Cancel an existing Cal.com booking by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {"type": "string"},
                    "cancellation_reason": {"type": "string"},
                },
                "required": ["booking_uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calendar_list",
            "description": "List calendar events in a time range. Default writable calendar is Personal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "from": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                    "to": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                },
                "required": ["from", "to"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calendar_create",
            "description": "Create a new calendar event in a writable calendar, default Personal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                    "end": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                },
                "required": ["summary", "start", "end"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calendar_edit",
            "description": "Edit or move an existing event using its uid. Use start/end to move the event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "uid": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                    "end": {"type": "string", "description": "ISO 8601 datetime with timezone offset"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "calendar_delete",
            "description": "Delete an existing event using its uid from a writable calendar, default Personal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "uid": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "tasks_list",
            "description": "List tasks from a task-enabled calendar. If calendar is omitted, use the default tasks calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "tasks_create",
            "description": "Create a new task with optional due date, priority, and description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "title": {"type": "string"},
                    "due": {"type": "string", "description": "ISO 8601 datetime with timezone offset or YYYY-MM-DD"},
                    "priority": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "tasks_edit",
            "description": "Edit an existing task by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "uid": {"type": "string"},
                    "title": {"type": "string"},
                    "due": {"type": "string"},
                    "priority": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "tasks_complete",
            "description": "Mark a task as completed by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "uid": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "tasks_delete",
            "description": "Delete a task by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {"type": "string"},
                    "uid": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "contacts_search",
            "description": "Search contacts by name, email, phone, or organization.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "addressbook": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "contacts_create",
            "description": "Create a contact with optional email, phone, organization, title, and note.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "addressbook": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "organization": {"type": "string"},
                    "title": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "contacts_edit",
            "description": "Edit a contact by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {"type": "string"},
                    "addressbook": {"type": "string"},
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "organization": {"type": "string"},
                    "title": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "contacts_delete",
            "description": "Delete a contact by uid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {"type": "string"},
                    "addressbook": {"type": "string"},
                },
                "required": ["uid"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "files_list",
            "description": "List files or folders at a Nextcloud path. Use /Shared as the default discovery root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "files_search",
            "description": "Search Nextcloud files by query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "files_get",
            "description": "Read a Nextcloud file by path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    ]
    filtered: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")
        if name == "current_datetime":
            if enabled["datetime"]:
                filtered.append(tool)
            continue
        if name.startswith("calcom_"):
            if enabled["calcom"]:
                filtered.append(tool)
            continue
        if name.startswith("calendar_"):
            if enabled["calendar"]:
                filtered.append(tool)
            continue
        if name.startswith("tasks_"):
            if enabled["tasks"]:
                filtered.append(tool)
            continue
        if name.startswith("files_"):
            if enabled["files"]:
                filtered.append(tool)
            continue
        if name.startswith("contacts_"):
            if enabled["contacts"]:
                filtered.append(tool)
            continue
        filtered.append(tool)
    return filtered

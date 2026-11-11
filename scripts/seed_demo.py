#!/usr/bin/env python3
"""Create or remove only the reserved Demo Showcase tenant.

Passwords for newly-created accounts are written once to a private file.
The script never queries existing projects, users or calls outside the demo.
"""

import argparse
import json
import os
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid5

import bcrypt
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.services.demo_showcase import DEMO_TENANT_ID, DEMO_TENANT_SLUG
from app.services.pricing import DEFAULT_XAI_VOICE_PRICING_PER_MINUTE

TENANT = str(DEMO_TENANT_ID)
PROJECTS = (
    ("appuntamenti", "Gestione appuntamenti (demo)", "support", "Gestisci richieste generiche di appuntamento con cortesia, senza raccogliere dati sensibili."),
    ("recruiting", "Recruiting - screening candidati (demo)", "recruiting", "Raccogli disponibilita e competenze per una prima selezione, senza promettere un esito."),
    ("retail", "Assistenza clienti retail (demo)", "support", "Aiuta i clienti con informazioni generiche su ordini e resi."),
    ("ristorante", "Prenotazioni ristorante (demo)", "other", "Raccogli numero di persone e preferenze per una richiesta di prenotazione."),
)
USERS = (("giulia.ventresi@example.com", "Giulia Ventresi", "admin"),
         ("elia.valdieri@example.com", "Elia Valdieri", "creator"),
         ("nora.bellani@example.com", "Nora Bellani", "power_user"))
NAMES = ("Arianna Valdieri", "Luca Ventresi", "Viola Merlani", "Tommaso Bellani", "Elisa Selvani", "Davide Rinaldi")
QUESTIONS = (
    "Buongiorno, vorrei sapere se posso fissare un appuntamento per la prossima settimana.",
    "Buongiorno, vorrei avere informazioni sulla candidatura e sui prossimi passaggi.",
    "Salve, ho una domanda sui tempi previsti per un ordine.",
    "Buonasera, vorrei prenotare un tavolo per quattro persone.",
)
ANSWERS = (
    "Certamente, mi indichi il giorno preferito e le comunichero le opzioni disponibili.",
    "Certo, possiamo raccogliere la sua disponibilita per un primo colloquio.",
    "Posso aiutarla. Mi descriva brevemente la sua richiesta.",
    "Con piacere. Mi dica la data e l'orario desiderati.",
)


def ident(value):
    return str(uuid5(DEMO_TENANT_ID, value))


def execute(reset, password_file, dry_run=False):
    dsn = get_settings().database_url
    created_passwords = {}
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (624970193,))
            cur.execute("SELECT set_config('app.tenant_id', %s, true), set_config('app.is_super_admin', 'false', true)", (TENANT,))
            cur.execute("SELECT name, slug FROM tenants WHERE id = %s", (TENANT,))
            tenant = cur.fetchone()
            if tenant and tenant != ("Demo Showcase", DEMO_TENANT_SLUG):
                raise RuntimeError("Reserved demo tenant ID belongs to a different tenant; no changes made")
            if reset:
                if tenant:
                    cur.execute("DELETE FROM calls WHERE tenant_id = %s", (TENANT,))
                    cur.execute("DELETE FROM tenants WHERE id = %s AND slug = %s", (TENANT, DEMO_TENANT_SLUG))
                if dry_run:
                    conn.rollback()
                return 0

            cur.execute("INSERT INTO tenants (id, name, slug, settings) VALUES (%s, %s, %s, %s::jsonb) ON CONFLICT (id) DO NOTHING",
                        (TENANT, "Demo Showcase", DEMO_TENANT_SLUG, json.dumps({"show_costs_to_tenant_admin": True, "included_minutes": 1000})))
            for email, full_name, role in USERS:
                user_id = ident("user:" + email)
                cur.execute("SELECT id FROM users WHERE id = %s AND tenant_id = %s", (user_id, TENANT))
                if not cur.fetchone():
                    password = secrets.token_urlsafe(24)
                    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                    cur.execute("INSERT INTO users (id,tenant_id,email,full_name,role,password_hash,email_verified) VALUES (%s,%s,%s,%s,%s,%s,true)",
                                (user_id, TENANT, email, full_name, role, password_hash))
                    created_passwords[email] = password

            now = datetime.now(timezone.utc).replace(microsecond=0)
            for key, name, kind, prompt in PROJECTS:
                project_id = ident("project:" + key)
                cur.execute("""INSERT INTO projects (id,tenant_id,name,slug,type,description,prompt_a,prompt_b,voice_name,language,voice_engine,call_direction,output_config)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'demo','it','demo','inbound','{}'::jsonb) ON CONFLICT (id) DO NOTHING""",
                    (project_id, TENANT, name, "showcase-" + key, kind, "Dati dimostrativi fittizi", prompt, "Estrai un breve riepilogo della richiesta."))
                cur.execute("SELECT id FROM projects WHERE id = %s AND tenant_id = %s", (project_id, TENANT))
                if not cur.fetchone():
                    raise RuntimeError("Reserved project ID collision; no changes made")
                for version, state in ((1, "archived"), (2, "published")):
                    cur.execute("""INSERT INTO agent_versions (id,project_id,tenant_id,version_number,status,prompt_a,prompt_b,voice_name,language,voice_engine,published_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'demo','it','demo',%s) ON CONFLICT (id) DO NOTHING""",
                        (ident(f"version:{key}:{version}"), project_id, TENANT, version, state,
                         prompt + (" Rispondi con sintesi e chiarezza." if version == 2 else ""),
                         "Estrai un breve riepilogo della richiesta.", now if version == 2 else None))

            rng = random.Random(84129)
            rate = DEFAULT_XAI_VOICE_PRICING_PER_MINUTE["grok-voice-latest"]
            cur.execute("SELECT value FROM settings WHERE key = %s", ("xai_voice_pricing_per_minute",))
            pricing = cur.fetchone()
            if pricing and pricing[0]:
                try:
                    configured = float(json.loads(pricing[0]).get("grok-voice-latest", rate))
                    if configured > 0:
                        rate = configured
                except (ValueError, TypeError, AttributeError):
                    pass
            for i in range(60):
                p = i % len(PROJECTS)
                key = PROJECTS[p][0]
                call_id = ident(f"call:{i}")
                start = now - timedelta(days=i // 2, hours=1 + rng.randrange(8), minutes=rng.randrange(60))
                seconds = rng.randint(30, 240)
                state = "declined" if i % 13 == 0 else "cancelled" if i % 17 == 0 else "completed"
                cost = round(seconds * rate / 60, 4) if state == "completed" else 0
                cur.execute("""INSERT INTO calls (id,tenant_id,project_id,agent_version_id,phone_number,status,started_at,ended_at,created_at,
                    voice_engine,direction,origin,channel,billable_audio_seconds,cost_usd,cost_source,session_model)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'demo','inbound','voice_simulation','demo',%s,%s,'demo_estimate','grok-voice-latest')
                    ON CONFLICT (id) DO NOTHING RETURNING id""",
                    (call_id, TENANT, ident("project:" + key), ident(f"version:{key}:2"),
                     f"+39 02 0000 {i:04d}", state, start, start + timedelta(seconds=seconds), start, seconds, cost))
                inserted = cur.fetchone()
                if inserted and state == "completed":
                    lines = (("user", f"Sono {NAMES[i % len(NAMES)]}. {QUESTIONS[p]}"), ("assistant", ANSWERS[p]))
                    for n, (role, content) in enumerate(lines):
                        cur.execute("INSERT INTO transcripts (call_id,role,content,timestamp) VALUES (%s,%s,%s,%s)",
                                    (call_id, role, content, start + timedelta(seconds=5 + n * 9)))

            if created_passwords and not dry_run:
                fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(created_passwords, f, indent=2)
                    f.write("\n")
            if dry_run:
                conn.rollback()
    return len(created_passwords)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Remove the demo tenant and its data")
    parser.add_argument("--dry-run", action="store_true", help="Run in a rolled-back transaction")
    parser.add_argument("--password-file", default=None)
    args = parser.parse_args()
    password_file = args.password_file or str(Path.home() / f".voxlyne-demo-passwords-{secrets.token_hex(4)}.json")
    created = execute(args.reset, password_file, args.dry_run)
    if args.dry_run:
        print("Demo dry run completed; transaction rolled back.")
    else:
        print("Demo removed." if args.reset else f"Demo seed complete. New accounts: {created}. Password file: {password_file if created else 'unchanged'}")


if __name__ == "__main__":
    main()

"""Integration test against a disposable PostgreSQL cluster, never production."""

import os
import subprocess
import tempfile
import unittest
import asyncio
import json
import socket
import pwd
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg2
from databases import Database
from fastapi import HTTPException
from starlette.requests import Request

from app.config import get_settings
from app.middleware.auth_middleware import CurrentUser, get_current_user
from app.routers.api import _serialize_project
from app.services.demo_showcase import DEMO_TENANT_ID
from app.services.analytics_service import AnalyticsService
from scripts.seed_demo import execute

BIN = Path("/usr/lib/postgresql/18/bin")
SCHEMA = """
CREATE TABLE tenants (id uuid PRIMARY KEY, name text, slug text UNIQUE, settings jsonb);
CREATE TABLE users (id uuid PRIMARY KEY, tenant_id uuid REFERENCES tenants ON DELETE CASCADE, email text UNIQUE,
 full_name text, role text, password_hash text, email_verified boolean);
CREATE TABLE projects (id uuid PRIMARY KEY, tenant_id uuid REFERENCES tenants ON DELETE CASCADE,
 name text, slug text UNIQUE, type text, description text, prompt_a text, prompt_b text,
 voice_name text, language text, voice_engine text, call_direction text, output_config jsonb,
 is_active boolean DEFAULT true);
CREATE TABLE agent_versions (id uuid PRIMARY KEY, project_id uuid REFERENCES projects ON DELETE CASCADE,
 tenant_id uuid REFERENCES tenants ON DELETE CASCADE, version_number int, status text,
 prompt_a text, prompt_b text, voice_name text, language text, voice_engine text, published_at timestamptz,
 UNIQUE (project_id, version_number));
CREATE TABLE calls (id uuid PRIMARY KEY, tenant_id uuid REFERENCES tenants ON DELETE CASCADE,
 project_id uuid REFERENCES projects ON DELETE CASCADE, agent_version_id uuid REFERENCES agent_versions ON DELETE SET NULL,
 phone_number text, status text, started_at timestamptz, ended_at timestamptz, created_at timestamptz,
 voice_engine text, direction text, origin text, channel text, billable_audio_seconds int,
 cost_usd numeric, cost_source text, session_model text,
 duration_seconds int GENERATED ALWAYS AS (extract(epoch FROM (ended_at - started_at))::int) STORED);
CREATE TABLE transcripts (id serial PRIMARY KEY, call_id uuid REFERENCES calls ON DELETE CASCADE,
 role text, content text, timestamp timestamptz);
CREATE TABLE settings (key text PRIMARY KEY, value text);
CREATE TABLE records (id uuid PRIMARY KEY, call_id uuid REFERENCES calls ON DELETE CASCADE,
 crm_synced boolean DEFAULT false, appointment_scheduled boolean DEFAULT false);
"""


class DemoAccessTest(unittest.TestCase):
    def test_restricts_demo_accounts_and_preserves_other_tenants(self):
        demo = CurrentUser(id=uuid4(), email="admin@example.test", role="admin", tenant_id=DEMO_TENANT_ID)
        other = CurrentUser(id=uuid4(), email="other@example.test", role="admin", tenant_id=uuid4())

        def request(path, method="GET"):
            return Request({"type": "http", "method": method, "path": path, "headers": []})

        with patch("app.middleware.auth_middleware._auth_middleware", new=AsyncMock(return_value=demo)):
            self.assertEqual(asyncio.run(get_current_user(request("/api/analytics/dashboard"), None)), demo)
            for path, method in (("/api/outbound/call", "POST"), ("/api/tenants/credentials", "GET")):
                with self.assertRaises(HTTPException) as error:
                    asyncio.run(get_current_user(request(path, method), None))
                self.assertEqual(error.exception.status_code, 403)
        with patch("app.middleware.auth_middleware._auth_middleware", new=AsyncMock(return_value=other)):
            self.assertEqual(asyncio.run(get_current_user(request("/api/outbound/call", "POST"), None)), other)

    def test_legacy_doubly_encoded_output_config(self):
        expected = {"pdf": {"enabled": False}}
        self.assertEqual(_serialize_project({"output_config": json.dumps(json.dumps(expected))})["output_config"], expected)


@unittest.skipUnless((BIN / "initdb").exists(), "PostgreSQL test binaries unavailable")
class SeedDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="ascolta-demo-test-")
        cls.root = Path(cls.tmp.name)
        cls.data = cls.root / "pg"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        subprocess.run([str(BIN / "initdb"), "-D", str(cls.data), "-A", "trust", "--no-locale"], check=True, capture_output=True)
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(cls.data), "-l", str(cls.root / "postgres.log"),
                        "-o", f"-F -k {cls.root} -c listen_addresses=127.0.0.1 -p {port}", "-w", "start"], check=True, capture_output=True)
        cls.dsn = f"postgresql://{pwd.getpwuid(os.getuid()).pw_name}@127.0.0.1:{port}/postgres"
        cls.env = patch.dict(os.environ, {"DATABASE_URL": cls.dsn, "OPENAI_API_KEY": "test", "OPENAI_PROJECT_ID": "test"})
        cls.env.start()
        get_settings.cache_clear()
        with psycopg2.connect(cls.dsn) as conn, conn.cursor() as cur:
            cur.execute(SCHEMA)

    @classmethod
    def tearDownClass(cls):
        get_settings.cache_clear()
        cls.env.stop()
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(cls.data), "-m", "fast", "-w", "stop"], check=True, capture_output=True)
        cls.tmp.cleanup()

    def test_seed_idempotence_and_reset_are_tenant_scoped(self):
        other_tenant, other_project = str(uuid4()), str(uuid4())
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO tenants VALUES (%s, 'Fixture', 'fixture', '{}')", (other_tenant,))
            cur.execute("INSERT INTO projects (id, tenant_id, name, slug) VALUES (%s,%s,'Fixture non demo','fixture-project')", (other_project, other_tenant))
        passwords = str(self.root / "passwords.json")
        self.assertEqual(execute(False, passwords), 3)
        self.assertEqual(execute(False, passwords), 0)
        self.assertEqual(os.stat(passwords).st_mode & 0o777, 0o600)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            for table, count in (("projects", 4), ("users", 3), ("agent_versions", 8), ("calls", 60)):
                cur.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (str(DEMO_TENANT_ID),))
                self.assertEqual(cur.fetchone()[0], count)
            cur.execute("SELECT count(*) FROM calls WHERE tenant_id=%s AND (origin <> 'voice_simulation' OR phone_number NOT LIKE '+000%%')", (str(DEMO_TENANT_ID),))
            self.assertEqual(cur.fetchone()[0], 0)

        async def check_analytics():
            db = Database(self.dsn)
            await db.connect()
            try:
                with patch("app.services.analytics_service.get_database", return_value=db):
                    service = AnalyticsService()
                    demo = await service.get_dashboard_stats(DEMO_TENANT_ID)
                    global_stats = await service.get_dashboard_stats()
                    self.assertEqual(demo["total_calls_month"], 60)
                    self.assertEqual(demo["active_projects"], 4)
                    self.assertEqual(global_stats["total_calls_month"], 0)
                    self.assertEqual(global_stats["active_projects"], 1)
                    self.assertEqual((await service.get_call_trends("month", DEMO_TENANT_ID))["total_calls"], 60)
                    self.assertEqual((await service.get_call_trends("month"))["total_calls"], 0)
                    self.assertEqual(len(await service.get_project_stats(DEMO_TENANT_ID)), 4)
                    self.assertEqual(len(await service.get_project_stats()), 1)
                    self.assertEqual(sum((await service.get_call_stats_by_status(DEMO_TENANT_ID)).values()), 60)
                    self.assertEqual(sum((await service.get_call_stats_by_status()).values()), 0)
            finally:
                await db.disconnect()

        asyncio.run(check_analytics())
        execute(True, passwords)
        execute(True, passwords)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT name FROM projects WHERE id=%s AND tenant_id=%s", (other_project, other_tenant))
            self.assertEqual(cur.fetchone()[0], "Fixture non demo")
            cur.execute("SELECT count(*) FROM tenants WHERE id=%s", (str(DEMO_TENANT_ID),))
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

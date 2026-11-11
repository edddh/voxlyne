# Ascolta

Ascolta is an open-source, self-hosted platform for building and operating AI telephone agents. It combines SIP-ready voice runtimes, project configuration, prompt versioning, retrieval-backed knowledge bases, browser simulations, call analytics, and controlled integrations with external systems.

It is designed for developers and teams that want to own their telephony workflow while connecting their chosen AI and telephony providers. Ascolta does not serve models itself: it orchestrates external provider APIs. The repository contains no production credentials, recordings, transcripts, customer names, or live configuration. The included scenarios and calls are synthetic.

## Focus

Ascolta provides the operational layer around an AI telephone agent:

- Version prompts, compare changes, test them, and roll them back.
- Simulate conversations against synthetic data before enabling an integration.
- Inspect retrieval and tool calls before an agent acts on an external system.
- Keep external actions typed, auditable, idempotent, and suitable for approval workflows.
- Route a conversation to a specialist workflow or human operator with structured context.
- Connect inbound telephony through provider-specific SIP and webhook adapters.

## Included Demo Scenarios

- Appointment scheduling
- Candidate screening
- Retail customer support
- Restaurant reservations

All names, email addresses, phone numbers, calls, transcripts, and costs created by the demo seed are fictional.

## Technology

- Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, pgvector
- React, Vite, Ant Design
- Docker Compose for local dependencies

## Local Setup

Prerequisites: Python 3.11+, Node.js 20+, Docker with Docker Compose, and PostgreSQL.

```bash
git clone https://github.com/edddh/ascolta.git
cd ascolta
cp .env.example .env
docker compose up -d postgres minio
.venv/bin/alembic upgrade heads
.venv/bin/python scripts/create_admin.py --email admin@example.test --name "Local Administrator"
.venv/bin/uvicorn app.main:app --reload --port 8091
```

Build the administration UI separately:

```bash
cd admin-ui
npm install
npm run build
```

Do not commit `.env`, credential exports, database dumps, recordings, or call transcripts. `.env.example` contains placeholders only.

## Safe Demo Data

Create a synthetic workspace for screenshots and local evaluation:

```bash
.venv/bin/python scripts/seed_demo.py
```

The seed is idempotent and creates only the `Demo Showcase` workspace. Remove only its synthetic data with:

```bash
.venv/bin/python scripts/seed_demo.py --reset
```

Demo projects cannot start real calls and contain no provider credentials.

## Tests

```bash
.venv/bin/pytest tests/test_demo_seed.py
```

## Roadmap

The upcoming work is in [ROADMAP.md](ROADMAP.md).

## Security

Do not submit credentials or personal information in issues. See [SECURITY.md](SECURITY.md).

## License

Apache-2.0. See [LICENSE](LICENSE).

The name and logo policy is in [TRADEMARKS.md](TRADEMARKS.md).

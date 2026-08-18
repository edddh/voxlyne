"""kernel Fase 2: agent_versions, inbound_endpoints, calls.agent_version_id

Revision ID: 22d55674165c
Revises: c6cc30521e18
Create Date: 2026-08-18 18:00:38.630296

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22d55674165c'
down_revision: Union[str, Sequence[str], None] = 'c6cc30521e18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Fase 2 del piano (kernel): il pezzo che manca perche' due numeri di due
tenant diversi rispondano davvero in modo diverso, invece che con
DEFAULT_PROMPT_A/impostazioni globali (il P0 di ADR-0001, qui risolto
solo per il percorso OpenAI SIP - webhook.py).

Non reinventa `projects` (gia' contiene prompt/voce/lingua per agente,
vedi ADR-0001: "non riscrivere il percorso funzionante"): agent_versions
ne congela un'istantanea immutabile al momento della pubblicazione;
inbound_endpoints risolve un numero/URI SIP a un project_id/tenant_id.

RLS: agent_versions e inbound_endpoints hanno tenant_id (via project_id
per la prima, diretto per la seconda) e seguono lo stesso pattern delle
migration precedenti (d6554c3662e6, 0e3297fb271d) - SELECT+INSERT+UPDATE+
DELETE stavolta insieme, fin dall'inizio, non in due passaggi come e'
successo la volta scorsa.
"""

TENANT_CHECK = (
    "current_setting('app.is_super_admin', true) = 'true' "
    "OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_versions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published', 'archived')),
            prompt_a TEXT NOT NULL,
            prompt_b TEXT,
            consent_message TEXT,
            voice_name VARCHAR(50),
            language VARCHAR(10),
            voice_engine VARCHAR(50),
            output_config JSONB,
            published_at TIMESTAMPTZ,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (project_id, version_number)
        )
        """
    )
    op.execute("CREATE INDEX idx_agent_versions_project ON agent_versions (project_id)")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_agent_versions_one_published
        ON agent_versions (project_id)
        WHERE status = 'published'
        """
    )

    op.execute(
        """
        CREATE TABLE inbound_endpoints (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            identifier VARCHAR(255) NOT NULL UNIQUE,
            identifier_type VARCHAR(20) NOT NULL DEFAULT 'sip'
                CHECK (identifier_type IN ('sip', 'phone_number')),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_inbound_endpoints_project ON inbound_endpoints (project_id)")

    op.execute("ALTER TABLE calls ADD COLUMN agent_version_id UUID REFERENCES agent_versions(id) ON DELETE SET NULL")

    for table in ("agent_versions", "inbound_endpoints"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation_select ON {table} FOR SELECT USING ({TENANT_CHECK})")
        op.execute(f"CREATE POLICY tenant_isolation_insert ON {table} FOR INSERT WITH CHECK ({TENANT_CHECK})")
        op.execute(f"CREATE POLICY tenant_isolation_update ON {table} FOR UPDATE USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})")
        op.execute(f"CREATE POLICY tenant_isolation_delete ON {table} FOR DELETE USING ({TENANT_CHECK})")


def downgrade() -> None:
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS agent_version_id")
    op.execute("DROP TABLE IF EXISTS inbound_endpoints")
    op.execute("DROP TABLE IF EXISTS agent_versions")

"""RLS: policy di scrittura mancanti su users/projects/prompt_blocks/template_assignments

Revision ID: 0e3297fb271d
Revises: d6554c3662e6
Create Date: 2026-08-18 17:39:16.343518

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e3297fb271d'
down_revision: Union[str, Sequence[str], None] = 'd6554c3662e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Corregge un errore di ragionamento della migration precedente
(d6554c3662e6): avevo scritto solo policy FOR SELECT, assumendo che
INSERT/UPDATE/DELETE restassero "non ristretti" in loro assenza. E'
il contrario: con FORCE ROW LEVEL SECURITY, un comando senza alcuna
policy applicabile viene NEGATO di default, non permesso.

Ha mandato in crash-loop il servizio in ambiente di sviluppo: il bootstrap di
avvio fa un INSERT su projects (nessuna policy INSERT = negato), e
separatamente l'UPDATE last_login_at del login falliva allo stesso
modo per ogni credenziale corretta (da cui "credenziali non valide"
anche con la password giusta - l'eccezione RLS veniva probabilmente
assorbita a monte e mostrata come fallimento generico).

Aggiunge policy esplicite per INSERT/UPDATE/DELETE, stessa condizione
della policy SELECT gia' esistente (incluso il caso "risorsa condivisa"
per projects/prompt_blocks).
"""

TABLES_WITH_SHARED_NULL_TENANT = {
    "projects": "is_template = TRUE",
    "prompt_blocks": "is_public = TRUE",
}
TABLES_STRICT = ["users", "template_assignments"]

TENANT_CHECK = (
    "current_setting('app.is_super_admin', true) = 'true' "
    "OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    for table in TABLES_STRICT:
        check = TENANT_CHECK
        op.execute(f"CREATE POLICY tenant_isolation_insert ON {table} FOR INSERT WITH CHECK ({check})")
        op.execute(f"CREATE POLICY tenant_isolation_update ON {table} FOR UPDATE USING ({check}) WITH CHECK ({check})")
        op.execute(f"CREATE POLICY tenant_isolation_delete ON {table} FOR DELETE USING ({check})")

    for table, shared_condition in TABLES_WITH_SHARED_NULL_TENANT.items():
        check = f"{TENANT_CHECK} OR ({shared_condition})"
        op.execute(f"CREATE POLICY tenant_isolation_insert ON {table} FOR INSERT WITH CHECK ({check})")
        op.execute(f"CREATE POLICY tenant_isolation_update ON {table} FOR UPDATE USING ({check}) WITH CHECK ({check})")
        op.execute(f"CREATE POLICY tenant_isolation_delete ON {table} FOR DELETE USING ({check})")


def downgrade() -> None:
    for table in TABLES_STRICT + list(TABLES_WITH_SHARED_NULL_TENANT.keys()):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_update ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_delete ON {table}")

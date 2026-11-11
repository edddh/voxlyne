"""RLS su users, projects, prompt_blocks, template_assignments

Revision ID: d6554c3662e6
Revises: f747b97a60bd
Create Date: 2026-08-18 17:24:02.839181

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6554c3662e6'
down_revision: Union[str, Sequence[str], None] = 'f747b97a60bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Seconda barriera di isolamento tenant, oltre ai controlli applicativi
(check_tenant_access, aggiunti il 18/08 in api.py/calendar.py/crm.py/
outbound.py). Se un futuro endpoint dimentica il filtro tenant - ed e'
successo gia' oggi, due volte, in file diversi - Postgres nega comunque
l'accesso alla riga, non solo l'applicazione.

Scope deliberatamente limitato a SELECT su 4 tabelle dove non c'e' rischio
di rompere il percorso live:

- users, template_assignments: nessuna riga con tenant_id NULL se non il
  super_admin stesso (per progetto, non un bug).
- projects: i 3 INSERT nel codice includono sempre tenant_id, tranne i
  template (is_template=TRUE, tenant_id NULL per progetto - la visibilita'
  per tenant assegnato resta gestita dalla JOIN su template_assignments a
  livello applicativo, RLS non la reimplementa qui).
- prompt_blocks: stesso pattern, is_public=TRUE + tenant_id NULL sono i
  blocchi condivisi globali, documentati come tali nel codice.

`calls` resta FUORI di proposito: il percorso inbound (webhook.py) non
popola tenant_id (gap gia' in ADR-0001/FEATURE_MATRIX.md), e FORCE ROW
LEVEL SECURITY bloccherebbe quell'INSERT - romperebbe l'unico flusso di
chiamata funzionante, quello protetto come baseline di regressione. Va
aggiunta insieme al resolver di Fase 2, non prima.

INSERT/UPDATE/DELETE non hanno policy qui (solo USING, nessun WITH CHECK):
la vulnerabilita' dimostrata oggi era di lettura (un tenant vedeva dati di
un altro), non di scrittura. Le policy di scrittura sono un secondo giro,
deliberatamente non incluso in questa migration.

FORCE ROW LEVEL SECURITY e' necessario perche' il ruolo applicativo (voxlyne)
e' anche il proprietario delle tabelle (verificato: pg_tables.tableowner) -
senza FORCE, un proprietario bypassa sempre le policy.

api_keys resta FUORI anch'essa, per un motivo diverso da calls: l'auth via
X-API-Key (AuthMiddleware.__call__ -> validate_api_key) legge quella
tabella per scoprire CHI e' l'utente, prima che si possa impostare
app.tenant_id nella sessione - FORCE RLS la bloccherebbe alla radice.
In piu' quel percorso assegna role="api_key", che non e' nemmeno un
valore valido di UserRole: sembra gia' un feature incompleta/non
testata, non vale la pena rischiare di romperla per aggiungere RLS a
una tabella il cui utilizzo reale e' incerto.
"""

TABLES_WITH_SHARED_NULL_TENANT = {
    "projects": "is_template = TRUE",
    "prompt_blocks": "is_public = TRUE",
}
TABLES_STRICT = ["users", "template_assignments"]


def upgrade() -> None:
    for table in TABLES_STRICT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_select ON {table}
            FOR SELECT
            USING (
                current_setting('app.is_super_admin', true) = 'true'
                OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            """
        )

    for table, shared_condition in TABLES_WITH_SHARED_NULL_TENANT.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_select ON {table}
            FOR SELECT
            USING (
                current_setting('app.is_super_admin', true) = 'true'
                OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                OR ({shared_condition})
            )
            """
        )


def downgrade() -> None:
    for table in TABLES_STRICT + list(TABLES_WITH_SHARED_NULL_TENANT.keys()):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_select ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

"""add escalated call status

Revision ID: a3905808ab22
Revises: ab11d01c42f3
Create Date: 2026-08-19 09:46:35.540012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3905808ab22'
down_revision: Union[str, Sequence[str], None] = 'ab11d01c42f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer (20/08): dopo aver costruito il rilevamento vero di "Rifiutata"
per xai_sip_direct (riattacco senza parlare, o richiesta esplicita di
operatore umano - vedi runtime_workers/realtime_service.py::
_finalize_call_record e il nuovo tool request_human_operator) - "se uno
ha chiesto l'operatore umano forse bisognerebbe dire qualcosa tipo
'Inoltro'". Giusto: chi chiede un umano non e' lo stesso esito di chi
riattacca senza dire nulla - buttarli insieme in 'declined' perdeva la
distinzione. Nuovo valore 'escalated' per il caso "vuole un operatore";
'declined' ora significa solo "nessun coinvolgimento" (riattacco
silenzioso, o in futuro un consenso rifiutato esplicitamente, per "oppure
rifiuta il consenso nel caso venga richiesto" di maintainer).
"""


def upgrade() -> None:
    op.execute("ALTER TABLE calls DROP CONSTRAINT calls_status_check")
    op.execute("""
        ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN (
            'pending_consent',
            'consented',
            'in_progress',
            'completed',
            'processing',
            'processed',
            'declined',
            'escalated',
            'cancelled'
        ))
    """)


def downgrade() -> None:
    op.execute("UPDATE calls SET status = 'declined' WHERE status = 'escalated'")
    op.execute("ALTER TABLE calls DROP CONSTRAINT calls_status_check")
    op.execute("""
        ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN (
            'pending_consent',
            'consented',
            'in_progress',
            'completed',
            'processing',
            'processed',
            'declined',
            'cancelled'
        ))
    """)

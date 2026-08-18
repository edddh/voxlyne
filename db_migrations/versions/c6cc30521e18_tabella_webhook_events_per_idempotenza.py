"""tabella webhook_events per idempotenza

Revision ID: c6cc30521e18
Revises: 0e3297fb271d
Create Date: 2026-08-18 17:44:52.964094

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6cc30521e18'
down_revision: Union[str, Sequence[str], None] = '0e3297fb271d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
Deliberatamente senza tenant_id e senza RLS: e' una tabella di sistema
(dedup di eventi webhook), non dati di un tenant - stessa categoria di
`_migrations`, non di `calls`/`projects`. Niente da imparare qui dalla
lezione delle migration precedenti, appunto perche' non c'entra RLS.
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE webhook_events (
            id BIGSERIAL PRIMARY KEY,
            provider VARCHAR(50) NOT NULL,
            event_id VARCHAR(255) NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (provider, event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_webhook_events_received_at ON webhook_events (received_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_events")

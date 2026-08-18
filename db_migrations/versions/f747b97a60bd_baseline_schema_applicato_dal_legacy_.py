"""baseline: schema applicato dal legacy runner (001-010)

Revision ID: f747b97a60bd
Revises: 
Create Date: 2026-08-18 16:48:37.179613

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f747b97a60bd'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op di proposito.

    Questa revisione non applica schema: rappresenta lo stato del database
    dopo l'esecuzione dei 12 file SQL storici in migrations/*.sql
    (001_initial_schema.sql ... 010_tenant_credentials_index.sql), applicati
    dal runner legacy (run-migrations.sh, tracciamento in `_migrations`).

    Quei file restano congelati come record storico - non vanno rinumerati
    né modificati (vedi migrations/README-legacy.md). Il DB reale è già
    stato "stampato" su questa revisione con `alembic stamp head`, senza
    ri-eseguire nulla. Ogni nuova modifica allo schema, da qui in avanti,
    passa da una nuova revisione Alembic (`alembic revision`), mai da un
    nuovo file in migrations/.
    """
    pass


def downgrade() -> None:
    """Nessun downgrade possibile dalla baseline: rifare da un backup."""
    pass

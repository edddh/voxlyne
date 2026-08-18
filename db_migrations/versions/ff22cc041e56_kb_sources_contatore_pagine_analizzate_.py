"""kb_sources: contatore pagine analizzate per progresso live

Revision ID: ff22cc041e56
Revises: 8d2eea496817
Create Date: 2026-08-18 20:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff22cc041e56'
down_revision: Union[str, Sequence[str], None] = '8d2eea496817'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer (18/08): "non va bene che non si sappia il numero parziale delle
pagine, potrebbe essere andato in crash?" - con l'indicizzazione
precedente (tutto scritto in blocco a fine crawl) non c'era modo di
distinguere "sta ancora lavorando" da "e' bloccato" per un crawl lungo
(centinaia di pagine). pages_crawled si aggiorna ad ogni pagina
processata (indexer.py), non solo a fine corsa - un valore che cresce e'
la prova che il processo e' vivo.
"""


def upgrade() -> None:
    op.execute("ALTER TABLE kb_sources ADD COLUMN pages_crawled INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE kb_sources DROP COLUMN IF EXISTS pages_crawled")

"""kb_sources: intervallo di ricrawl schedulato

Revision ID: 8d2eea496817
Revises: e1cc4132c384
Create Date: 2026-08-18 19:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d2eea496817'
down_revision: Union[str, Sequence[str], None] = 'e1cc4132c384'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer (18/08): "nella configurazione devo poter indicare ogni quanto
faccio il crawling e quante pagine" - crawl_max_pages esisteva gia'
(acfbe417a42a); manca la cadenza. NULL = una tantum (nessun ricrawl
automatico, comportamento di oggi), un intero = ogni tot ore. Il
recrawl_at, non solo l'intervallo, e' quello che lo scheduler
(app/services/rag/scheduler.py) interroga direttamente - evita di dover
ricalcolare "ultimo indexed_at + intervallo" ad ogni tick e si aggiorna
da solo dopo ogni run, schedulato o manuale (reindex via API).
"""


def upgrade() -> None:
    op.execute("ALTER TABLE kb_sources ADD COLUMN recrawl_interval_hours INTEGER")
    op.execute("ALTER TABLE kb_sources ADD COLUMN next_crawl_at TIMESTAMPTZ")
    op.execute("CREATE INDEX idx_kb_sources_next_crawl ON kb_sources (next_crawl_at) WHERE next_crawl_at IS NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE kb_sources DROP COLUMN IF EXISTS next_crawl_at")
    op.execute("ALTER TABLE kb_sources DROP COLUMN IF EXISTS recrawl_interval_hours")

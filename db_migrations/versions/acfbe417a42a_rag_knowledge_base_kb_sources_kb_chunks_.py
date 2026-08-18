"""RAG knowledge base: kb_sources, kb_chunks, pgvector

Revision ID: acfbe417a42a
Revises: 22d55674165c
Create Date: 2026-08-18 19:23:41.384537

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'acfbe417a42a'
down_revision: Union[str, Sequence[str], None] = '22d55674165c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


"""
maintainer (18/08, dopo il test live Grok/Exampleville): "mi piacerebbe poter
lavorare sulla funzione RAG e avere la base dati dal crawl del comune di
Exampleville" - con il vincolo esplicito che la funzionalita' deve restare
generica/configurabile da pannello admin (progetto -> fonti -> indice),
Exampleville e' solo il primo tenant che la popola, non un caso hardcoded.

Un kb_source per progetto puo' essere un URL da crawlare o un file
caricato (upload); entrambi finiscono chunk-izzati ed embeddati in
kb_chunks. Niente tabella "knowledge_bases" separata: un progetto ha al
piu' una KB implicita (l'insieme delle sue kb_sources) - un livello di
indirezione in piu' senza un bisogno reale oggi (nessun caso d'uso di
piu' KB per progetto), aggiungerlo se/quando serve davvero.

pgvector: richiede `CREATE EXTENSION vector`, che richiede superuser (o
un'estensione marcata "trusted" - non garantito su tutte le distro/
versioni). Il ruolo applicativo `ascolta` non e' superuser (verificato
18/08) - se questa migration fallisce qui, l'estensione va creata a mano
una tantum da un superuser (`sudo -u postgres psql -d ascolta -c "CREATE
EXTENSION IF NOT EXISTS vector"`) prima di rilanciare `alembic upgrade
head`.

embedding vector(1536): dimensione di OpenAI text-embedding-3-small
(vedi app/services/rag/embeddings.py) - se in futuro si cambia modello di
embedding con dimensione diversa, serve una migration a parte per
ricreare la colonna (pgvector non supporta ALTER della dimensione).

Indice HNSW (non IVFFlat): non richiede un training set minimo prima di
essere utile, a differenza di IVFFlat che degrada su poche righe - scelta
adatta a un sistema dove ogni progetto parte da zero chunk.
"""

TENANT_CHECK = (
    "current_setting('app.is_super_admin', true) = 'true' "
    "OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE kb_sources (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
            source_type VARCHAR(20) NOT NULL CHECK (source_type IN ('url', 'upload')),
            url TEXT,
            filename TEXT,
            crawl_max_pages INTEGER NOT NULL DEFAULT 20,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'indexed', 'failed')),
            error TEXT,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            indexed_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX idx_kb_sources_project ON kb_sources (project_id)")

    op.execute(
        """
        CREATE TABLE kb_chunks (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            source_id UUID NOT NULL REFERENCES kb_sources(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            origin_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_kb_chunks_project ON kb_chunks (project_id)")
    op.execute(
        """
        CREATE INDEX idx_kb_chunks_embedding_hnsw
        ON kb_chunks USING hnsw (embedding vector_cosine_ops)
        """
    )

    for table in ("kb_sources", "kb_chunks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation_select ON {table} FOR SELECT USING ({TENANT_CHECK})")
        op.execute(f"CREATE POLICY tenant_isolation_insert ON {table} FOR INSERT WITH CHECK ({TENANT_CHECK})")
        op.execute(f"CREATE POLICY tenant_isolation_update ON {table} FOR UPDATE USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})")
        op.execute(f"CREATE POLICY tenant_isolation_delete ON {table} FOR DELETE USING ({TENANT_CHECK})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kb_chunks")
    op.execute("DROP TABLE IF EXISTS kb_sources")

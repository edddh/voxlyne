"""
Ascolta - RAG embeddings client.

Same "strictly per-tenant, no .env fallback" rule as every other provider
credential in this codebase (see app/services/agent_versions.py's
resolve_provider_api_key docstring) - the embedding key is a separate
credential from the voice/xai or voice/openai_realtime ones (service_type
"llm", provider "openai"), because a tenant may reasonably want to use a
different OpenAI key/project for embeddings than for live calls, or use
xAI for voice but still need an OpenAI key here (xAI doesn't currently
expose an embeddings endpoint).

text-embedding-3-small, 1536 dims - matches the `vector(1536)` column in
kb_chunks (db_migrations/versions/acfbe417a42a). Changing the model needs
a migration to change that dimension too, pgvector doesn't allow altering
it in place.
"""

import logging
from typing import List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


async def resolve_embedding_api_key(tenant_id: UUID) -> Optional[str]:
    if not tenant_id:
        return None
    from app.services.credentials.manager import CredentialsManager

    manager = CredentialsManager()
    creds = await manager._fetch_db_credentials(
        entity_type="tenant", entity_id=tenant_id, service_type="llm", provider="openai",
    )
    return creds.get("api_key") if creds else None


async def embed_texts(tenant_id: UUID, texts: List[str]) -> List[List[float]]:
    """
    Embeds a batch of texts with the tenant's own OpenAI key. Raises
    ValueError if no llm/openai credential is stored for the tenant - the
    caller (indexer.py) marks the kb_source as 'failed' with that message
    rather than silently skipping it or using another tenant's key.
    """
    if not texts:
        return []

    api_key = await resolve_embedding_api_key(tenant_id)
    if not api_key:
        raise ValueError(
            f"No llm/openai credential stored for tenant {tenant_id} - cannot generate "
            f"embeddings. Add one under Credenziali tenant (servizio 'llm', provider 'openai')."
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    # OpenAI's embeddings endpoint accepts up to 2048 inputs per request,
    # but keep batches modest so one bad chunk doesn't fail the whole page.
    batch_size = 96
    vectors: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend([item.embedding for item in resp.data])
    return vectors


async def embed_query(tenant_id: UUID, query: str) -> List[float]:
    vectors = await embed_texts(tenant_id, [query])
    return vectors[0]

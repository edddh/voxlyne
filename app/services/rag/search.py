"""
Voxlyne - RAG semantic search.

pgvector's `<=>` operator is cosine *distance* (0 = identical, 2 =
opposite) - matches the hnsw index built with vector_cosine_ops in the
migration (an index built for a different distance operator wouldn't be
used by the planner for this query). similarity = 1 - distance, more
intuitive for a caller/tool result than raw distance.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.database.db import get_database
from app.services.rag.embeddings import embed_query

logger = logging.getLogger(__name__)


async def search_knowledge_base(
    project_id: UUID,
    tenant_id: Optional[UUID],
    query: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Returns the top_k most relevant chunks for `query` within project_id's
    knowledge base, ordered by similarity descending. Empty list if the
    project has no indexed chunks yet, or if the tenant has no llm/openai
    embedding credential (propagates embed_query's ValueError to the
    caller - see its docstring - callers decide whether that's a hard
    error or a "no results" for the end user).
    """
    query_vector = await embed_query(tenant_id, query)
    vec_literal = "[" + ",".join(str(x) for x in query_vector) + "]"

    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        rows = await db.fetch_all(
            """
            SELECT content, origin_url, 1 - (embedding <=> :qvec) AS similarity
            FROM kb_chunks
            WHERE project_id = :project_id
            ORDER BY embedding <=> :qvec
            LIMIT :top_k
            """,
            {"project_id": str(project_id), "qvec": vec_literal, "top_k": top_k},
        )
    return [dict(r) for r in rows]

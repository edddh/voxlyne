"""
Ascolta - RAG indexer: turns a kb_source (url or upload) into kb_chunks.

Runs as an asyncio.create_task() background job kicked off by the admin
API (app/routers/knowledge_base.py), same "no external task queue"
pattern already used for post-call processing elsewhere in this codebase
- acceptable at this scale (one admin action -> one background index job,
not a high-volume queue).
"""

import logging
from typing import Optional
from uuid import UUID

from app.database.db import get_database
from app.services.rag.chunking import chunk_text
from app.services.rag.crawler import crawl
from app.services.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)


async def _mark_status(source_id: UUID, status: str, error: Optional[str] = None, chunk_count: Optional[int] = None) -> None:
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        fields = {"status": status, "error": error, "id": str(source_id)}
        set_clause = "status = :status, error = :error"
        if status == "indexed":
            # Reschedule the next run here (not in the scheduler loop
            # itself) so both a scheduled run and a manual "reindex now"
            # click push next_crawl_at forward the same way - a manual
            # reindex shouldn't leave the old, now-stale next_crawl_at in
            # place and fire again a few minutes later.
            set_clause += """, indexed_at = now(),
                next_crawl_at = CASE WHEN recrawl_interval_hours IS NOT NULL
                    THEN now() + (recrawl_interval_hours || ' hours')::interval
                    ELSE NULL END"""
        if chunk_count is not None:
            set_clause += ", chunk_count = :chunk_count"
            fields["chunk_count"] = chunk_count
        await db.execute(f"UPDATE kb_sources SET {set_clause} WHERE id = :id", fields)


async def _store_chunks(source_id: UUID, project_id: UUID, tenant_id: Optional[UUID], pages: list[tuple[str, str]]) -> int:
    """pages: list of (origin_url_or_None, text). Chunks, embeds, inserts."""
    db = get_database()

    all_chunks: list[tuple[str, Optional[str]]] = []  # (content, origin_url)
    for origin_url, text in pages:
        for chunk in chunk_text(text):
            all_chunks.append((chunk, origin_url))

    if not all_chunks:
        return 0

    vectors = await embed_texts(tenant_id, [c for c, _ in all_chunks])

    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        # Replace whatever this source indexed before (re-index = full
        # refresh, not an append - stale chunks from a page that no
        # longer exists on the site shouldn't linger forever).
        await db.execute("DELETE FROM kb_chunks WHERE source_id = :id", {"id": str(source_id)})
        for i, ((content, origin_url), vector) in enumerate(zip(all_chunks, vectors)):
            await db.execute(
                """
                INSERT INTO kb_chunks (source_id, project_id, tenant_id, chunk_index, content, embedding, origin_url)
                VALUES (:source_id, :project_id, :tenant_id, :chunk_index, :content, :embedding, :origin_url)
                """,
                {
                    "source_id": str(source_id),
                    "project_id": str(project_id),
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "chunk_index": i,
                    "content": content,
                    "embedding": "[" + ",".join(str(x) for x in vector) + "]",
                    "origin_url": origin_url,
                },
            )
    return len(all_chunks)


async def index_url_source(source_id: UUID, project_id: UUID, tenant_id: Optional[UUID], url: str, max_pages: int) -> None:
    await _mark_status(source_id, "processing")
    try:
        pages = [(page_url, text) async for page_url, text in crawl(url, max_pages=max_pages)]
        if not pages:
            await _mark_status(source_id, "failed", error="Nessuna pagina indicizzabile trovata (crawl vuoto)")
            return
        count = await _store_chunks(source_id, project_id, tenant_id, pages)
        await _mark_status(source_id, "indexed", chunk_count=count)
        logger.info(f"kb_source {source_id}: crawled {len(pages)} pages, {count} chunks")
    except Exception as e:
        logger.exception(f"kb_source {source_id} (url) indexing failed")
        await _mark_status(source_id, "failed", error=str(e))


async def index_upload_source(source_id: UUID, project_id: UUID, tenant_id: Optional[UUID], filename: str, text: str) -> None:
    await _mark_status(source_id, "processing")
    try:
        count = await _store_chunks(source_id, project_id, tenant_id, [(None, text)])
        await _mark_status(source_id, "indexed", chunk_count=count)
        logger.info(f"kb_source {source_id}: uploaded {filename}, {count} chunks")
    except Exception as e:
        logger.exception(f"kb_source {source_id} (upload) indexing failed")
        await _mark_status(source_id, "failed", error=str(e))

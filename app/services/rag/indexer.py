"""
Ascolta - RAG indexer: turns a kb_source (url or upload) into kb_chunks.

Runs as an asyncio.create_task() background job kicked off by the admin
API (app/routers/knowledge_base.py), same "no external task queue"
pattern already used for post-call processing elsewhere in this codebase
- acceptable at this scale (one admin action -> one background index job,
not a high-volume queue).

Indexes incrementally, page by page (chunk_count/pages_crawled updated
after each page), not "collect everything, write once at the end".
maintainer (18/08), watching a ~700-page crawl of comune.exampleville.it run
with no visible progress: "non va bene che non si sappia il numero
parziale delle pagine, potrebbe essere andato in crash?" - a long crawl
with only a single write at the very end is indistinguishable from a
hung process the whole time it runs. This also means a crash partway
through a large crawl doesn't lose everything already fetched.
"""

import logging
from typing import Optional
from uuid import UUID

from app.database.db import get_database
from app.services.rag.chunking import chunk_text
from app.services.rag.crawler import crawl
from app.services.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)


async def _mark_status(source_id: UUID, status: str, error: Optional[str] = None) -> None:
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
        await db.execute(f"UPDATE kb_sources SET {set_clause} WHERE id = :id", fields)


async def _store_page_chunks(
    source_id: UUID, project_id: UUID, tenant_id: Optional[UUID], origin_url: Optional[str], text: str,
) -> int:
    """Chunks+embeds+inserts ONE page's text, returns how many chunks it produced."""
    pieces = chunk_text(text)
    if not pieces:
        return 0

    vectors = await embed_texts(tenant_id, pieces)

    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        # chunk_index continues across pages of the same source - read the
        # current max instead of restarting at 0 each call, so chunks stay
        # orderable/unique even though they're inserted incrementally now.
        current_max = await db.fetch_val(
            "SELECT COALESCE(MAX(chunk_index), -1) FROM kb_chunks WHERE source_id = :id", {"id": str(source_id)},
        )
        for i, (content, vector) in enumerate(zip(pieces, vectors)):
            await db.execute(
                """
                INSERT INTO kb_chunks (source_id, project_id, tenant_id, chunk_index, content, embedding, origin_url)
                VALUES (:source_id, :project_id, :tenant_id, :chunk_index, :content, :embedding, :origin_url)
                """,
                {
                    "source_id": str(source_id),
                    "project_id": str(project_id),
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "chunk_index": current_max + 1 + i,
                    "content": content,
                    "embedding": "[" + ",".join(str(x) for x in vector) + "]",
                    "origin_url": origin_url,
                },
            )
    return len(pieces)


async def _bump_progress(source_id: UUID, pages_delta: int, chunks_delta: int) -> None:
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        await db.execute(
            """
            UPDATE kb_sources
            SET pages_crawled = pages_crawled + :pages_delta, chunk_count = chunk_count + :chunks_delta
            WHERE id = :id
            """,
            {"pages_delta": pages_delta, "chunks_delta": chunks_delta, "id": str(source_id)},
        )


async def index_url_source(source_id: UUID, project_id: UUID, tenant_id: Optional[UUID], url: str, max_pages: int) -> None:
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        # Full refresh, not an append - stale chunks from a page no longer
        # on the site shouldn't linger. Done once, up front, not per-page
        # (a per-page delete+reinsert would make incremental progress
        # regress instead of grow while a big crawl is still running).
        await db.execute("DELETE FROM kb_chunks WHERE source_id = :id", {"id": str(source_id)})
        await db.execute(
            "UPDATE kb_sources SET status = 'processing', pages_crawled = 0, chunk_count = 0, error = NULL WHERE id = :id",
            {"id": str(source_id)},
        )

    total_chunks = 0
    total_pages = 0
    try:
        async for page_url, text in crawl(url, max_pages=max_pages):
            total_pages += 1
            page_chunks = await _store_page_chunks(source_id, project_id, tenant_id, page_url, text)
            total_chunks += page_chunks
            await _bump_progress(source_id, pages_delta=1, chunks_delta=page_chunks)

        if total_chunks == 0:
            await _mark_status(source_id, "failed", error="Nessuna pagina indicizzabile trovata (crawl vuoto)")
            return
        await _mark_status(source_id, "indexed")
        logger.info(f"kb_source {source_id}: crawled {total_pages} pages, {total_chunks} chunks")
    except Exception as e:
        logger.exception(f"kb_source {source_id} (url) indexing failed after {total_pages} pages / {total_chunks} chunks")
        await _mark_status(source_id, "failed", error=str(e))


async def index_upload_source(source_id: UUID, project_id: UUID, tenant_id: Optional[UUID], filename: str, text: str) -> None:
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        await db.execute("DELETE FROM kb_chunks WHERE source_id = :id", {"id": str(source_id)})
        await db.execute(
            "UPDATE kb_sources SET status = 'processing', pages_crawled = 0, chunk_count = 0, error = NULL WHERE id = :id",
            {"id": str(source_id)},
        )
    try:
        count = await _store_page_chunks(source_id, project_id, tenant_id, None, text)
        await _bump_progress(source_id, pages_delta=1, chunks_delta=count)
        if count == 0:
            await _mark_status(source_id, "failed", error="Nessun contenuto indicizzabile dopo il chunking")
            return
        await _mark_status(source_id, "indexed")
        logger.info(f"kb_source {source_id}: uploaded {filename}, {count} chunks")
    except Exception as e:
        logger.exception(f"kb_source {source_id} (upload) indexing failed")
        await _mark_status(source_id, "failed", error=str(e))

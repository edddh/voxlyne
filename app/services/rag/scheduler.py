"""
Ascolta - RAG recrawl scheduler.

Same background-task pattern as app/services/session_cleanup.py (a single
asyncio loop started/stopped from the app's lifespan, no external task
queue) - checks periodically for kb_sources whose next_crawl_at is due
and re-runs index_url_source() for them. Only 'url' sources can be
scheduled (an 'upload' has no remote content to re-fetch - reuploading is
a manual action, see app/routers/knowledge_base.py's reindex endpoint).
"""

import asyncio
import logging
from typing import Optional

from app.database.db import get_database
from app.services.rag.indexer import index_url_source

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 900  # 15 minutes - recrawl intervals are in hours, no need to poll more often


class RagRecrawlScheduler:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("RAG recrawl scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RAG recrawl scheduler stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._run_due_sources()
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("RAG recrawl scheduler loop error")
                await asyncio.sleep(60)

    async def _run_due_sources(self) -> None:
        db = get_database()
        async with db.transaction():
            await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
            due = await db.fetch_all(
                """
                SELECT id, project_id, tenant_id, url, crawl_max_pages
                FROM kb_sources
                WHERE source_type = 'url' AND next_crawl_at IS NOT NULL AND next_crawl_at <= now()
                  AND status != 'processing'
                """
            )
        if not due:
            return
        logger.info(f"RAG scheduler: {len(due)} source(s) due for recrawl")
        for source in due:
            asyncio.create_task(
                index_url_source(
                    source["id"], source["project_id"], source["tenant_id"],
                    source["url"], source["crawl_max_pages"],
                )
            )

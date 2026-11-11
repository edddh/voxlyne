"""
Voxlyne - RAG web crawler.

Deliberately simple breadth-first, same-domain-only crawler with a hard
page cap (kb_sources.crawl_max_pages, default 20) - this indexes a
tenant's own public site content (e.g. maintainer's original ask: "avere la
base dati dal crawl del comune di Exampleville"), not a general-purpose
scraper.

Two strategies, tried in this order:
1. kPortal CMS API (app/services/rag/kportal.py) - many Italian municipal
   sites (comune.exampleville.it included) are Angular SPAs that render
   nothing server-side, so plain HTML fetching yields ~empty pages; this
   template exposes its real content via a JSON API + sitemap.xml
   instead. Detected automatically (kapiUrl found in the site's env.js),
   not hardcoded to Exampleville - any site on this template benefits.
2. Plain HTML link-crawl with BeautifulSoup extraction (the fallback for
   every regular, server-rendered site) - a site that renders its content
   client-side and ISN'T on the kPortal template still won't index well
   here (would need a headless browser), a known remaining limit.

Respects robots.txt (best-effort: if robots.txt is unreachable or
unparseable, treats the site as fully allowed rather than blocking
indexing - a municipal site with a broken robots.txt is far more likely
than one that deliberately wants to block us).
"""

import asyncio
import logging
import re
import urllib.robotparser
from typing import AsyncIterator, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.rag.extractors import extract_html_text
from app.services.rag.kportal import (
    DETAIL_SLUG_TO_OTYPE,
    DETAIL_URL_RE,
    OTYPE_TO_SLUG,
    _slugify,
    discover_kapi_url,
    discover_novita_items,
    discover_sitemap_urls,
    fetch_detail_by_otype_id,
    fetch_kapi_detail,
)


def _is_fetchable_detail_url(url: str) -> bool:
    """True only for URLs whose slug maps to a known otype - i.e. ones
    fetch_kapi_detail() can actually resolve (see its DETAIL_SLUG_TO_OTYPE
    lookup). DETAIL_URL_RE alone also matches slugs like "argomento"
    (topic) that aren't in that mapping and would just waste a fetch."""
    match = DETAIL_URL_RE.search(url)
    return bool(match and match.group("slug").lower() in DETAIL_SLUG_TO_OTYPE)

logger = logging.getLogger(__name__)

USER_AGENT = "VoxlyneBot/1.0 (+https://voxlyne.example.invalid.com)"

# Below this, extracted text is almost certainly an empty SPA shell (e.g.
# "Portale istituzionale" and nothing else) rather than real content -
# found live against comune.exampleville.it (18/08), where the un-rendered
# root page yielded exactly that. Not a scientific threshold, just clearly
# above "page title only, no body".
MIN_USEFUL_TEXT_LENGTH = 60

# Polite pause between requests to the SAME site being crawled - a crawl
# of a real municipal site's full sitemap (hundreds of pages) shouldn't
# hammer their server in a tight burst just because httpx can do that.
# Not configurable from the admin UI on purpose: this protects the target
# site, not something a tenant should be able to turn off to go faster.
REQUEST_DELAY_SECONDS = 0.3


async def _fetch_robots(client: httpx.AsyncClient, base_url: str) -> urllib.robotparser.RobotFileParser:
    parser = urllib.robotparser.RobotFileParser()
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        resp = await client.get(robots_url, timeout=10)
        if resp.status_code == 200:
            parser.parse(resp.text.splitlines())
        else:
            parser.allow_all = True
    except Exception:
        parser.allow_all = True
    return parser


def _same_domain(url: str, root_domain: str) -> bool:
    return urlparse(url).netloc == root_domain


_META_REFRESH_RE = re.compile(
    r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;"\']*;\s*url=([^"\'>]+)',
    re.IGNORECASE,
)


def _meta_refresh_target(html: str, base_url: str) -> str | None:
    """
    Some sites (e.g. comune.exampleville.it's homepage) redirect via <meta
    http-equiv="refresh"> instead of an HTTP redirect - httpx doesn't
    follow those on its own (they're not part of the HTTP response), so a
    naive fetch of such a page yields ~0 chars of content and stops there.
    """
    match = _META_REFRESH_RE.search(html)
    if not match:
        return None
    return urljoin(base_url, match.group(1).strip())


async def _resolve_real_start(client: httpx.AsyncClient, start_url: str) -> str:
    try:
        resp = await client.get(start_url)
        target = _meta_refresh_target(resp.text, start_url)
        return target or start_url
    except Exception:
        return start_url


async def _crawl_kportal(
    client: httpx.AsyncClient,
    robots: urllib.robotparser.RobotFileParser,
    real_start: str,
    kapi_url: str,
    root_domain: str,
    max_pages: int,
) -> AsyncIterator[tuple[str, str]]:
    # "sito/novita" (found 18/08) instead of sitemap.xml as the primary
    # discovery source: maintainer caught a real, currently-live article
    # (21/07/2026, CIE issuance hours) that simply wasn't in the site's
    # sitemap - proving it can silently lag behind real content. novita is
    # a paginated, aggregated listing (notizie+avvisi+comunicati-stampa),
    # newest first, and its first page matched "today" on a live check -
    # provably current in a way the sitemap wasn't. Falls back to the
    # sitemap only if a kPortal site doesn't expose this endpoint (some
    # installs may differ).
    novita_items = await discover_novita_items(client, real_start, max_items=max_pages * 2)

    count = 0
    if novita_items:
        for otype, item_id, title in novita_items:
            if count >= max_pages:
                break
            if count > 0:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

            detail = await fetch_detail_by_otype_id(client, kapi_url, otype, item_id)
            if not detail:
                continue
            detail_title, text = detail
            full_text = f"{detail_title}\n\n{text}" if detail_title else text
            if len(full_text.strip()) < MIN_USEFUL_TEXT_LENGTH:
                continue

            # Reconstruct the human-facing URL for citation purposes - not
            # load-bearing (the content already came from otype+id
            # directly), best-effort only.
            slug = OTYPE_TO_SLUG.get(otype)
            origin_url = (
                f"{real_start.rstrip('/')}/{slug}/{item_id}-{_slugify(detail_title or title)}"
                if slug else f"{kapi_url}sito/detail-no-live/{otype}/{item_id}"
            )
            yield (origin_url, full_text)
            count += 1
        return

    sitemap_urls = [u for u in await discover_sitemap_urls(client, real_start) if _same_domain(u, root_domain)]
    # Content-detail pages (the ones fetch_kapi_detail can actually pull
    # real text from) first - a sitemap's first entries are typically
    # listing/category pages (/sito/notizie, /sito/servizi...), which are
    # themselves empty SPA shells server-side; without this a small
    # max_pages would spend its whole budget on those and yield nothing.
    detail_urls = [u for u in sitemap_urls if _is_fetchable_detail_url(u)]
    other_urls = [u for u in sitemap_urls if not _is_fetchable_detail_url(u)]
    candidate_urls = (detail_urls + other_urls)[:max_pages] or [real_start]

    for url in candidate_urls:
        if count >= max_pages:
            break
        if not robots.can_fetch(USER_AGENT, url):
            continue

        if count > 0:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

        detail = await fetch_kapi_detail(client, url, kapi_url)
        if detail:
            title, text = detail
            full_text = f"{title}\n\n{text}" if title else text
            if len(full_text.strip()) >= MIN_USEFUL_TEXT_LENGTH:
                yield (url, full_text)
                count += 1
            continue

        # Not a recognized content-detail URL (e.g. a listing/category
        # page) - try plain HTML extraction, it may still carry some
        # server-rendered text even on an SPA site.
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception:
            continue
        if "text/html" not in resp.headers.get("content-type", ""):
            continue
        text = extract_html_text(resp.text)
        if len(text.strip()) >= MIN_USEFUL_TEXT_LENGTH:
            yield (url, text)
            count += 1


async def _crawl_plain_html(
    client: httpx.AsyncClient,
    robots: urllib.robotparser.RobotFileParser,
    real_start: str,
    root_domain: str,
    max_pages: int,
) -> AsyncIterator[tuple[str, str]]:
    visited: Set[str] = set()
    queue = [real_start]

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not robots.can_fetch(USER_AGENT, url):
            logger.info(f"robots.txt disallows {url}, skipping")
            continue

        if visited:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            continue

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            continue

        refresh_target = _meta_refresh_target(resp.text, url)
        if refresh_target and _same_domain(refresh_target, root_domain) and refresh_target not in visited:
            queue.insert(0, refresh_target)
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        text = extract_html_text(resp.text)
        if len(text.strip()) >= MIN_USEFUL_TEXT_LENGTH:
            yield (url, text)

        if len(visited) >= max_pages:
            break

        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            if _same_domain(link, root_domain) and link not in visited:
                queue.append(link)


async def crawl(start_url: str, max_pages: int = 20) -> AsyncIterator[tuple[str, str]]:
    """Yields (url, extracted_text) for up to max_pages pages reachable from start_url, same domain only."""
    root_domain = urlparse(start_url).netloc

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20,
    ) as client:
        robots = await _fetch_robots(client, start_url)
        real_start = await _resolve_real_start(client, start_url)

        kapi_url = await discover_kapi_url(client, real_start)
        if kapi_url:
            logger.info(f"kPortal CMS detected at {real_start} (kapi={kapi_url}) - using sitemap+API strategy")
            async for item in _crawl_kportal(client, robots, real_start, kapi_url, root_domain, max_pages):
                yield item
            return

        async for item in _crawl_plain_html(client, robots, real_start, root_domain, max_pages):
            yield item

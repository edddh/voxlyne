"""
Voxlyne - kPortal CMS content API support (AGID municipal portal template).

maintainer (18/08): "avevo gia' risolto tutto in earlier-prototype". Ported per ADR-0002
(port the algorithm, discard mono-tenant assumptions) from
earlier-prototype-elevenlabs/sync_scenario_rag.py, which already solved exactly the
problem crawler.py hit on comune.exampleville.it: many Italian municipal
sites (kPortal / "Portale Istituzionale" AGID template - not
Exampleville-specific, the same otype/detail-API shape shows up across many
comuni using this CMS) render content client-side via Angular, so the raw
HTML a plain crawler fetches is empty. The site still serves its real
content as JSON through a "kapi" REST API + a normal sitemap.xml listing
the content pages - this module finds both and uses them together, no
headless browser needed.

Kept generic on purpose (same instruction as the RAG feature as a whole -
"generalizza... tramite configurazione del pannello admin"): this
activates automatically for ANY site built on this template (detected via
env.js's kapiUrl, not a hardcoded Exampleville URL), and crawler.py falls back
to plain HTML extraction for every other kind of site.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "VoxlyneBot/1.0 (+https://voxlyne.example.invalid.com)"
DEFAULT_KAPI_DEPTH = 2

# URL shape kPortal uses for a content detail page, e.g.
# /sito/notizia/12345-qualcosa - the slug says which content type it is,
# the numeric id is what the kapi detail endpoint wants.
DETAIL_URL_RE = re.compile(r"/sito/(?P<slug>[a-z0-9-]+)/(?P<id>\d+)(?:-[^/]+)?", re.IGNORECASE)

# slug -> kPortal's internal content-type id ("otype"). Same mapping
# earlier-prototype already reverse-engineered - stable across kPortal sites since
# it's part of the shared CMS product, not something each comune defines
# itself.
DETAIL_SLUG_TO_OTYPE = {
    "notizia": 5829,
    "notizie": 5829,
    "avviso": 5882,
    "avvisi": 5882,
    "comunicato-stampa": 5833,
    "comunicati-stampa": 5833,
    "evento": 5830,
    "eventi": 5830,
    "documento": 5831,
    "documenti": 5831,
    "servizio": 5827,
    "servizi": 5827,
}


OTYPE_TO_SLUG = {v: k for k, v in DETAIL_SLUG_TO_OTYPE.items() if k in {"notizia", "avviso", "comunicato-stampa", "evento", "documento", "servizio"}}


def _slugify(text: str) -> str:
    text = re.sub(r"[àá]", "a", text.lower())
    text = re.sub(r"[èé]", "e", text)
    text = re.sub(r"[ìí]", "i", text)
    text = re.sub(r"[òó]", "o", text)
    text = re.sub(r"[ùú]", "u", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _strip_html(text: str) -> str:
    if "<" in text and ">" in text:
        text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split()).strip()


async def discover_kapi_url(client: httpx.AsyncClient, seed_url: str) -> str:
    parsed = urlparse(seed_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    try:
        resp = await client.get(f"{root}/sito/assets/env.js", timeout=15)
        env_js = resp.text
    except Exception:
        return ""
    match = re.search(r'kapiUrl"\]\s*=\s*"([^"]+)"', env_js) or re.search(r'"kapiUrl"\s*:\s*"([^"]+)"', env_js)
    return match.group(1) if match else ""


async def discover_sitemap_urls(client: httpx.AsyncClient, seed_url: str) -> list[str]:
    parsed = urlparse(seed_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_locations: list[str] = []

    try:
        robots = await client.get(f"{root}/robots.txt", timeout=15)
        for line in robots.text.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap_locations.append(line.split(":", 1)[1].strip())
    except Exception:
        pass
    if not sitemap_locations:
        sitemap_locations.append(f"{root}/sitemap.xml")

    async def parse_sitemap(url: str) -> list[str]:
        try:
            resp = await client.get(url, timeout=15)
            root_el = ET.fromstring(resp.text)
        except Exception:
            return []
        urls: list[str] = []
        if root_el.tag.endswith("sitemapindex"):
            for loc in root_el.findall(".//{*}loc"):
                if loc.text:
                    urls.extend(await parse_sitemap(loc.text.strip()))
        else:
            for loc in root_el.findall(".//{*}loc"):
                if loc.text:
                    urls.append(loc.text.strip())
        return urls

    all_urls: list[str] = []
    for sm in sitemap_locations:
        all_urls.extend(await parse_sitemap(sm))
    return list(dict.fromkeys(all_urls))


async def fetch_detail_by_otype_id(
    client: httpx.AsyncClient, kapi_url: str, otype: int, item_id: int, depth: int = DEFAULT_KAPI_DEPTH,
) -> Optional[tuple[str, str]]:
    """Same as fetch_kapi_detail() but skips URL parsing - used when the
    caller already has (otype, id) directly from a kapi listing endpoint
    (see discover_novita_items()), which is exact instead of inferred
    from a URL slug."""
    detail_url = f"{kapi_url}sito/detail-no-live/{otype}/{item_id}?profondita={depth}"
    try:
        resp = await client.get(detail_url, headers={"Accept": "application/json"}, timeout=15)
        payload = resp.json()
    except Exception:
        return None

    results = payload.get("results") if isinstance(payload, dict) else None
    if not results or not isinstance(results, list) or not isinstance(results[0], dict):
        return None
    item = results[0]

    title = str(item.get("cntTitle") or item.get("titolo") or item.get("title") or "").strip()
    text_parts = []
    for key in ("cntDescrizione", "cntSommario", "cntTesto", "cntTestoCompleto", "cntTestoBreve", "cntContenuto"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            cleaned = _strip_html(raw)
            if cleaned:
                text_parts.append(cleaned)
    text = "\n".join(dict.fromkeys(text_parts)).strip()
    if not text:
        return None
    return title, text


async def fetch_kapi_detail(client: httpx.AsyncClient, url: str, kapi_url: str, depth: int = DEFAULT_KAPI_DEPTH) -> Optional[tuple[str, str]]:
    """Returns (title, text) if `url` is a kPortal content-detail page and the kapi has it, else None."""
    if not kapi_url:
        return None
    match = DETAIL_URL_RE.search(url)
    if not match:
        return None
    raw_id = match.group("id")
    if not raw_id.isdigit():
        return None
    otype = DETAIL_SLUG_TO_OTYPE.get(match.group("slug").lower())
    if not otype:
        return None
    return await fetch_detail_by_otype_id(client, kapi_url, otype, int(raw_id), depth)


async def discover_novita_items(
    client: httpx.AsyncClient, seed_url: str, max_items: int = 1000,
) -> list[tuple[int, int, str]]:
    """
    The "sito/novita" kapi endpoint (found 18/08, after the sitemap turned
    out to be missing a real, currently-live article - maintainer caught this
    live: an article from 21/07/2026 about CIE issuance hours simply
    wasn't in sitemap.xml, but IS reachable via detail-no-live once you
    know its otype/id) - an aggregated, paginated listing of notizie +
    avvisi + comunicati-stampa together, sorted newest first, that (unlike
    the sitemap) is provably complete and current: its first page's dates
    match "today" on a live check. Returns (otypeId, id, title) tuples,
    paginated (10 per page per this endpoint) up to max_items.
    """
    parsed = urlparse(seed_url)
    root = f"{parsed.scheme}://{parsed.netloc}/kapi/api/"
    items: list[tuple[int, int, str]] = []
    page = 0
    while len(items) < max_items:
        try:
            resp = await client.get(f"{root}sito/novita", params={"page": page}, timeout=15)
            data = resp.json()
        except Exception:
            break
        results = data.get("results") or []
        if not results:
            break
        for item in results:
            otype = item.get("otypeId")
            item_id = item.get("id")
            title = str(item.get("cntTitle") or "").strip()
            if isinstance(otype, int) and isinstance(item_id, int):
                items.append((otype, item_id, title))
        if page + 1 >= data.get("totalPages", 0):
            break
        page += 1
    return items[:max_items]

"""
Corpus Hub connectors — search + download open-access corpora.

Three adapters, all backend-mediated (the engine calls the upstream APIs,
never the browser):

  1. HuggingFace datasets-server — primary. Search + paginated text +
     metadata for hundreds of public datasets including Arabic + English
     Wikipedia. No key needed for public datasets. CORS-native, but we
     proxy through the engine for consistency and to keep the user's IP
     out of upstream logs.

  2. Wikipedia Action API — live article fetch for both ar + en. Useful
     when the user wants fresh articles (HF Wikipedia snapshot lags by
     months). No key.

  3. OPUS — parallel corpora (ar↔en translation pairs). The catalogue
     API has no keyword search, so we cache the ar/en catalogue locally
     and keyword-filter it.

License metadata is surfaced for every result so the user can decide
before downloading. We never redistribute — the user downloads to their
own machine for their own research.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #


@dataclass
class HubCorpus:
    """A single searchable corpus result from any hub."""

    hub: str            # "huggingface" | "wikipedia" | "opus"
    id: str             # hub-unique identifier
    title: str
    description: str
    language: str       # ISO code: "ar", "en", "ar-en", etc.
    size: str           # human-readable: "1.2 GB", "77k words", etc.
    license: str        # "CC-BY-SA 3.0", "CC0", "public domain", etc.
    download_url: str | None = None
    download_format: str = "txt"  # "txt", "zip", "jsonl", "html"
    extra: dict = field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    language: str
    hub: str
    total: int
    results: list[dict]


class DownloadResponse(BaseModel):
    """Download metadata — the actual bytes come back as a StreamingResponse
    from the /download endpoint, not as JSON."""

    hub: str
    corpus_id: str
    title: str
    format: str
    license: str
    size_hint: str


# --------------------------------------------------------------------------- #
# HuggingFace adapter
# --------------------------------------------------------------------------- #

HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"

# Curated catalogue of high-quality Arabic + English datasets on HuggingFace
# that we expose in the UI. Users can search these by keyword.
HF_CATALOGUE: list[dict] = [
    {
        "id": "wikimedia/wikipedia",
        "config_ar": "20231101.ar",
        "config_en": "20231101.en",
        "title": "Wikipedia (full dumps)",
        "description": "The complete Wikipedia corpus for 300+ languages, maintained by Wikimedia. Each article is a document. Excellent for general-reference frequency baselines.",
        "license": "CC-BY-SA 3.0",
        "size_hint": "~20 GB (en), ~1 GB (ar)",
    },
    {
        "id": "oscar-corpus/OSCAR-2301",
        "config_ar": "ar",
        "config_en": "en",
        "title": "OSCAR-2301 (Common Crawl, filtered)",
        "description": "Cleaned web-crawl text in 150+ languages. Much larger and more contemporary than Wikipedia, but noisier. Good for big-data frequency studies.",
        "license": "CC0 (data); see HF card for details",
        "size_hint": "~1 TB (en), ~50 GB (ar)",
    },
    {
        "id": "cc100",
        "config_ar": "ar",
        "config_en": "en",
        "title": "CC-100 (Common Crawl, 100 languages)",
        "description": "100-language Common Crawl corpus prepared for language modeling. Per-language .txt.xz files.",
        "license": "Unrestricted (preparation); see CC-100 site",
        "size_hint": "~87 GB (en), ~5.8 GB (ar)",
    },
    {
        "id": "EleutherAI/arabic_pile",
        "config_ar": "ar",
        "config_en": None,
        "title": "Arabic Pile (EleutherAI)",
        "description": "Large Arabic text corpus assembled for language modeling research.",
        "license": "See HF card (mixed)",
        "size_hint": "~3 GB",
    },
    # --- Open-source Arabic corpora (less computing-intensive) ---
    {
        "id": "arabic_billion_words",
        "config_ar": "ar",
        "config_en": None,
        "title": "Arabic Billion Words",
        "description": "Collection of 8 Arabic news sources (Aljazira, Almustaqbal, Alarabiya, etc.). ~1B words. Good for MSA reference. CC-BY.",
        "license": "CC-BY 4.0",
        "size_hint": "~2 GB",
    },
    {
        "id": "Osian/arabic_corpus",
        "config_ar": "ar",
        "config_en": None,
        "title": "OSIAN (Open Source International Arabic News)",
        "description": "~3.5M articles from 32 Arabic newspapers. CC-BY-NC. Good for news register studies.",
        "license": "CC-BY-NC 4.0",
        "size_hint": "~1.5 GB",
    },
    {
        "id": "HeshamHaroon/arabic_quotes",
        "config_ar": "ar",
        "config_en": None,
        "title": "Arabic Quotes Corpus",
        "description": "Small collection of Arabic quotes. Good for testing + teaching. Lightweight.",
        "license": "MIT",
        "size_hint": "~5 MB",
    },
    {
        "id": "wiki_qa",
        "config_ar": "ar",
        "config_en": "en",
        "title": "Arabic-English Wiki QA",
        "description": "Question-answer pairs from Wikipedia in Arabic + English. Good for parallel/bilingual studies.",
        "license": "CC-BY-SA 3.0",
        "size_hint": "~50 MB",
    },
    {
        "id": "arabic_text_classification",
        "config_ar": "ar",
        "config_en": None,
        "title": "Arabic Text Classification Corpus",
        "description": "News articles classified by topic (politics, sports, economy, culture). Good for register studies.",
        "license": "CC-BY 4.0",
        "size_hint": "~100 MB",
    },
]


async def _hf_search(query: str, language: str, limit: int) -> list[dict]:
    """Search the curated HF catalogue + full-text search inside Wikipedia."""
    results: list[dict] = []
    lang_code = "ar" if language == "ar" else "en"

    # 1. Filter the curated catalogue by keyword
    for entry in HF_CATALOGUE:
        config = entry.get(f"config_{lang_code}")
        if not config:
            continue
        if query.lower() in entry["title"].lower() or query.lower() in entry["description"].lower():
            results.append({
                "hub": "huggingface",
                "id": f"{entry['id']}:{config}",
                "title": entry["title"],
                "description": entry["description"],
                "language": lang_code,
                "size": entry["size_hint"],
                "license": entry["license"],
                "download_url": None,  # downloaded via /hub/download
                "download_format": "jsonl",
                "extra": {
                    "dataset": entry["id"],
                    "config": config,
                    "split": "train",
                },
            })

    # 2. Full-text search inside Wikipedia (if the query is specific enough)
    if len(results) < limit:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(
                    f"{HF_DATASETS_SERVER}/search",
                    params={
                        "dataset": "wikimedia/wikipedia",
                        "config": f"20231101.{lang_code}",
                        "split": "train",
                        "query": query,
                        "offset": 0,
                        "length": min(limit, 20),
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    for row in data.get("rows", []):
                        rdata = row.get("row", {})
                        title = rdata.get("title", "")
                        text = rdata.get("text", "")
                        snippet = text[:300] + "…" if len(text) > 300 else text
                        results.append({
                            "hub": "huggingface",
                            "id": f"wikipedia:{lang_code}:{row.get('row_idx', title)}",
                            "title": f"Wikipedia ({lang_code}): {title}",
                            "description": snippet,
                            "language": lang_code,
                            "size": f"{len(text):,} chars",
                            "license": "CC-BY-SA 3.0",
                            "download_url": None,
                            "download_format": "txt",
                            "extra": {
                                "dataset": "wikimedia/wikipedia",
                                "config": f"20231101.{lang_code}",
                                "title": title,
                                "text": text,
                            },
                        })
        except httpx.HTTPError as e:
            log.warning("hf_search_failed", error=str(e))

    return results[:limit]


async def _hf_download(dataset: str, config: str, split: str = "train", max_rows: int = 100) -> bytes:
    """Download rows from a HF dataset as a plain-text file."""
    texts: list[str] = []
    offset = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        while offset < max_rows:
            r = await client.get(
                f"{HF_DATASETS_SERVER}/rows",
                params={
                    "dataset": dataset,
                    "config": config,
                    "split": split,
                    "offset": offset,
                    "length": min(100, max_rows - offset),
                },
            )
            if r.status_code != 200:
                break
            data = r.json()
            rows = data.get("rows", [])
            if not rows:
                break
            for row in rows:
                rdata = row.get("row", {})
                title = rdata.get("title", "")
                text = rdata.get("text", "")
                if title:
                    texts.append(f"# {title}\n\n{text}")
                else:
                    texts.append(text)
            offset += len(rows)
            if len(rows) < 100:
                break

    content = "\n\n---\n\n".join(texts)
    return content.encode("utf-8")


# --------------------------------------------------------------------------- #
# Wikipedia live adapter
# --------------------------------------------------------------------------- #


async def _wikipedia_search(query: str, language: str, limit: int) -> list[dict]:
    """Search Wikipedia via the Action API."""
    lang_code = "ar" if language == "ar" else "en"
    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"https://{lang_code}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "origin": "*",
                    "srlimit": min(limit, 20),
                },
            )
            if r.status_code != 200:
                return results
            data = r.json()
            for item in data.get("query", {}).get("search", []):
                # Strip HTML tags from the snippet
                snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                results.append({
                    "hub": "wikipedia",
                    "id": f"wikipedia:{lang_code}:{item['title']}",
                    "title": f"Wikipedia ({lang_code}): {item['title']}",
                    "description": snippet[:300],
                    "language": lang_code,
                    "size": f"{item.get('wordcount', 0):,} words",
                    "license": "CC-BY-SA 3.0",
                    "download_url": None,
                    "download_format": "txt",
                    "extra": {
                        "lang": lang_code,
                        "title": item["title"],
                        "pageid": item.get("pageid"),
                    },
                })
    except httpx.HTTPError as e:
        log.warning("wikipedia_search_failed", error=str(e))
    return results


async def _wikipedia_download(lang: str, title: str) -> bytes:
    """Download a Wikipedia article as plain text (wikitext format)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
                "origin": "*",
            },
        )
        if r.status_code != 200:
            raise HTTPException(502, f"Wikipedia API returned {r.status_code}")
        data = r.json()
        if "error" in data:
            raise HTTPException(404, f"Wikipedia article not found: {title}")
        wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
        # Strip simple wikitext markup for a cleaner plain-text version
        text = _strip_wikitext(wikitext)
        return text.encode("utf-8")


def _strip_wikitext(wikitext: str) -> str:
    """Conservative wikitext → plain text conversion."""
    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", "", wikitext, flags=re.DOTALL)
    # Remove templates {{...}} (one level deep — nested templates are rare in articles)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    # Remove references <ref>...</ref>
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/>", "", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Strip link syntax: [[target|text]] → text, [[target]] → target
    text = re.sub(r"\[\[[^\]]*\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    # Remove external links: [http://... text] → text
    text = re.sub(r"\[https?://[^\s]+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://[^\s]+\]", "", text)
    # Remove bold/italic
    text = text.replace("'''", "").replace("''", "")
    # Remove headings markup but keep the text
    text = re.sub(r"^=+\s*(.*?)\s*=+$", r"\1", text, flags=re.MULTILINE)
    # Remove lists markup
    text = re.sub(r"^[\*#:;]+\s*", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# OPUS adapter (parallel corpora)
# --------------------------------------------------------------------------- #

OPUS_API = "https://opus.nlpl.eu/opusapi"

# Cached catalogue of OPUS corpora for ar + en (populated on first search)
_opus_cache: dict[str, list[dict]] = {"ar": [], "en": [], "ar-en": [], "last_fetched": 0.0}


async def _opus_fetch_catalogue() -> None:
    """Fetch the OPUS catalogue for Arabic + English (one-time, cached)."""
    import time
    now = time.time()
    # Cache for 24 hours
    if now - _opus_cache["last_fetched"] < 86400 and (_opus_cache["ar"] or _opus_cache["en"]):
        return

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Fetch Arabic corpora
            r = await client.get(OPUS_API, params={"source": "ar", "preprocessing": "moses"})
            if r.status_code == 200:
                _opus_cache["ar"] = r.json().get("corpora", [])
            # Fetch English corpora
            r = await client.get(OPUS_API, params={"source": "en", "preprocessing": "moses"})
            if r.status_code == 200:
                _opus_cache["en"] = r.json().get("corpora", [])
            # Fetch ar-en parallel corpora
            r = await client.get(OPUS_API, params={"source": "ar", "target": "en", "preprocessing": "moses"})
            if r.status_code == 200:
                _opus_cache["ar-en"] = r.json().get("corpora", [])
            _opus_cache["last_fetched"] = now
            log.info("opus_catalogue_fetched",
                     ar_count=len(_opus_cache["ar"]),
                     en_count=len(_opus_cache["en"]),
                     ar_en_count=len(_opus_cache["ar-en"]))
    except httpx.HTTPError as e:
        log.warning("opus_catalogue_fetch_failed", error=str(e))


async def _opus_search(query: str, language: str, limit: int) -> list[dict]:
    """Keyword-filter the cached OPUS catalogue."""
    await _opus_fetch_catalogue()

    # Pick the right cache slice
    if language == "ar":
        corpora = _opus_cache.get("ar", [])
    elif language == "en":
        corpora = _opus_cache.get("en", [])
    else:
        # parallel
        corpora = _opus_cache.get("ar-en", [])

    results: list[dict] = []
    q = query.lower()
    for c in corpora:
        name = c.get("corpus", "")
        if q and q not in name.lower():
            continue
        size_bytes = c.get("size", 0)
        size_hint = f"{size_bytes / 1_000_000:.1f} MB" if size_bytes else "unknown"
        pairs = c.get("alignment_pairs", 0)
        lang_display = f"{c.get('source', '?')}→{c.get('target', '?')}" if c.get("target") else c.get("source", "?")
        results.append({
            "hub": "opus",
            "id": f"opus:{name}:{c.get('source','?')}-{c.get('target','')}",
            "title": f"OPUS: {name}",
            "description": f"Parallel corpus {lang_display}, {pairs:,} sentence pairs. {size_hint}.",
            "language": lang_display,
            "size": size_hint,
            "license": "Per-corpus (see OPUS website)",
            "download_url": c.get("url"),
            "download_format": "zip",
            "extra": {
                "corpus": name,
                "source": c.get("source"),
                "target": c.get("target"),
                "version": c.get("version"),
                "url": c.get("url"),
            },
        })
        if len(results) >= limit:
            break
    return results


async def _opus_download(url: str) -> bytes:
    """Download an OPUS zip file. Returns the raw zip bytes — the caller
    extracts the .txt files."""
    async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(502, f"OPUS download failed: HTTP {r.status_code}")
        return r.content


def _extract_opus_zip(zip_bytes: bytes) -> bytes:
    """Extract .txt files from an OPUS moses zip and concatenate them."""
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith(".txt") and not name.startswith("."):
                with zf.open(name) as f:
                    texts.append(f"# File: {name}\n\n{f.read().decode('utf-8', errors='replace')}")
    if not texts:
        raise HTTPException(500, "No .txt files found in OPUS zip")
    return "\n\n---\n\n".join(texts).encode("utf-8")


# --------------------------------------------------------------------------- #
# API routes
# --------------------------------------------------------------------------- #


@router.get("/hub/search", response_model=SearchResponse)
async def hub_search(
    q: str = Query(..., min_length=1, description="Search query (keyword or topic)"),
    language: str = Query("en", pattern="^(ar|en|ar-en)$", description="Target language"),
    hub: str = Query("all", pattern="^(all|huggingface|wikipedia|opus)$", description="Which hub to search"),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    """Search across open-access corpus hubs.

    The engine proxies the upstream API calls so the user's IP stays out
    of upstream logs and CORS isn't an issue. Results include license
    metadata so the user can decide before downloading.
    """
    all_results: list[dict] = []

    if hub in ("all", "huggingface"):
        all_results.extend(await _hf_search(q, language, limit))
    if hub in ("all", "wikipedia") and language in ("ar", "en"):
        all_results.extend(await _wikipedia_search(q, language, limit))
    if hub in ("all", "opus"):
        all_results.extend(await _opus_search(q, language, limit))

    # Deduplicate by id
    seen: set[str] = set()
    deduped = []
    for r in all_results:
        if r["id"] not in seen:
            seen.add(r["id"])
            deduped.append(r)

    return SearchResponse(
        query=q,
        language=language,
        hub=hub,
        total=len(deduped),
        results=deduped[:limit],
    )


@router.get("/hub/catalogue")
async def hub_catalogue() -> dict:
    """Return the curated catalogue of available hubs + featured datasets.

    Useful for populating the UI before the user types a search query.
    """
    return {
        "hubs": [
            {
                "id": "huggingface",
                "name": "HuggingFace Datasets",
                "description": "Hundreds of public datasets including Wikipedia (ar/en), OSCAR, CC-100. Full-text search inside Wikipedia.",
                "requires_key": False,
                "languages": ["ar", "en"],
            },
            {
                "id": "wikipedia",
                "name": "Wikipedia (live)",
                "description": "Live article fetch from Arabic + English Wikipedia. CC-BY-SA 3.0.",
                "requires_key": False,
                "languages": ["ar", "en"],
            },
            {
                "id": "opus",
                "name": "OPUS Parallel Corpora",
                "description": "1,200+ parallel corpora (translation pairs) including ar↔en. Per-corpus licensing.",
                "requires_key": False,
                "languages": ["ar", "en", "ar-en"],
            },
        ],
        "featured": [
            {
                "hub": "huggingface",
                "id": "wikimedia/wikipedia:20231101.en",
                "title": "English Wikipedia (full dump)",
                "language": "en",
                "size": "~20 GB",
                "license": "CC-BY-SA 3.0",
            },
            {
                "hub": "huggingface",
                "id": "wikimedia/wikipedia:20231101.ar",
                "title": "Arabic Wikipedia (full dump)",
                "language": "ar",
                "size": "~1 GB",
                "license": "CC-BY-SA 3.0",
            },
            {
                "hub": "opus",
                "id": "opus:OpenSubtitles:ar-en",
                "title": "OpenSubtitles (ar↔en parallel)",
                "language": "ar-en",
                "size": "~2.4 GB",
                "license": "Per-corpus (see OPUS)",
            },
        ],
    }


from fastapi.responses import StreamingResponse  # noqa: E402 — late import to keep routes together


@router.get("/hub/download")
async def hub_download(
    hub: str = Query(..., pattern="^(huggingface|wikipedia|opus)$"),
    corpus_id: str = Query(..., description="The corpus id from the search result"),
    title: str = Query("", description="Human-readable title for the filename"),
    extra: str = Query("{}", description="JSON-encoded hub-specific params"),
) -> StreamingResponse:
    """Download a corpus from a hub. Returns a text/plain file (or zip for OPUS).

    The caller passes the `extra` dict from the search result back to us
    as a JSON string so we know how to fetch from the specific hub.
    """
    import urllib.parse

    try:
        extra_data = json.loads(extra) if extra else {}
    except json.JSONDecodeError:
        extra_data = {}

    # Build a safe filename
    safe_title = re.sub(r"[^\w\u0600-\u06FF\- ]", "_", title or corpus_id)[:80] or "corpus"
    safe_title = safe_title.strip().replace(" ", "_")

    if hub == "huggingface":
        dataset = extra_data.get("dataset", "")
        config = extra_data.get("config", "")
        if not dataset or not config:
            raise HTTPException(400, "HuggingFace download requires dataset + config in extra")

        # If this is a single Wikipedia article (extra has 'text'), return it directly
        if "text" in extra_data:
            content = extra_data["text"].encode("utf-8")
            fname = f"{safe_title}.txt"
        else:
            max_rows = extra_data.get("max_rows", 100)
            content = await _hf_download(dataset, config, max_rows=max_rows)
            fname = f"{safe_title}.txt"

        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{urllib.parse.quote(fname)}"'},
        )

    if hub == "wikipedia":
        lang = extra_data.get("lang", "en")
        wp_title = extra_data.get("title", "")
        if not wp_title:
            raise HTTPException(400, "Wikipedia download requires title in extra")
        content = await _wikipedia_download(lang, wp_title)
        fname = f"wikipedia_{lang}_{safe_title}.txt"
        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{urllib.parse.quote(fname)}"'},
        )

    if hub == "opus":
        url = extra_data.get("url")
        if not url:
            raise HTTPException(400, "OPUS download requires url in extra")
        zip_bytes = await _opus_download(url)
        # Extract the .txt files from the zip so the user gets plain text
        content = _extract_opus_zip(zip_bytes)
        fname = f"opus_{safe_title}.txt"
        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{urllib.parse.quote(fname)}"'},
        )

    raise HTTPException(400, f"Unknown hub: {hub}")

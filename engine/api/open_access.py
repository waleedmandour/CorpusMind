"""Open-access academic corpus download via API keys.

Supports downloading full-text content from:
  - CORE (core.ac.uk) — open-access research papers, full text
  - PMC E-utilities (ncbi.nlm.nih.gov) — biomedical full-text articles
  - arXiv (arxiv.org) — preprint search + PDF download
  - Leipzig Corpora (wortschatz-leipzig.de) — 250+ languages, plain text
  - Zenodo (zenodo.org) — research data repository
  - Semantic Scholar (semanticscholar.org) — academic paper discovery

API keys are stored in-memory (runtime, set from the UI) and never
written to disk. They take precedence over env-var keys.

All HTTP calls are proxied through the engine (not the browser) so:
  1. CORS is never an issue (CORE, Leipzig, arXiv have no CORS headers)
  2. The user's IP is not exposed to the upstream API
  3. Rate limiting can be enforced server-side
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.logging import get_logger

log = get_logger(__name__)
router = APIRouter()

# Runtime API key storage (in-memory, never on disk)
_runtime_keys: dict[str, str] = {}


def _get_key(source: str) -> str:
    """Return the API key for a source (runtime > env > empty)."""
    if source in _runtime_keys:
        return _runtime_keys[source]
    import os
    env_map = {
        "core": "CORPUSMIND_CORE_API_KEY",
        "pmc": "CORPUSMIND_PMC_API_KEY",
        "openalex": "CORPUSMIND_OPENALEX_API_KEY",
        "semantic_scholar": "CORPUSMIND_S2_API_KEY",
        "huggingface": "CORPUSMIND_HF_TOKEN",
    }
    env_var = env_map.get(source, f"CORPUSMIND_{source.upper()}_API_KEY")
    return os.environ.get(env_var, "")


# --------------------------------------------------------------------------- #
# API key management
# --------------------------------------------------------------------------- #


class SetKeyRequest(BaseModel):
    source: str = Field(..., description="Source ID: core, pmc, openalex, semantic_scholar, huggingface")
    api_key: str = Field(..., min_length=1)


class KeyStatus(BaseModel):
    source: str
    has_key: bool
    registration_url: str | None = None
    description: str = ""


SOURCE_INFO = {
    "core": {
        "name": "CORE",
        "description": "Open-access research papers with full text",
        "registration_url": "https://core.ac.uk/services/api",
        "registration_note": "Register with any email. Institutional email gets academic tier (5k requests/day).",
    },
    "pmc": {
        "name": "PubMed Central",
        "description": "Biomedical full-text articles (JATS XML)",
        "registration_url": "https://www.ncbi.nlm.nih.gov/account/register/",
        "registration_note": "Register with email + username + password. Get API key from NCBI account settings.",
    },
    "arxiv": {
        "name": "arXiv",
        "description": "Preprint server (physics, math, CS, linguistics). No API key needed.",
        "registration_url": None,
        "registration_note": "No registration required. Rate limit: 1 request/3 seconds.",
    },
    "leipzig": {
        "name": "Leipzig Corpora",
        "description": "250+ languages, plain-text sentences. No API key needed.",
        "registration_url": None,
        "registration_note": "No registration required. CC-BY 4.0 license.",
    },
    "zenodo": {
        "name": "Zenodo",
        "description": "Research data repository. No API key needed for reads.",
        "registration_url": "https://zenodo.org/signup/",
        "registration_note": "Optional registration for deposit. Reads are open.",
    },
    "openalex": {
        "name": "OpenAlex",
        "description": "Academic paper search + content. Optional key for higher limits.",
        "registration_url": "https://openalex.org/users/sign_up",
        "registration_note": "Optional. Register with email + password. Key from Settings → API.",
    },
    "semantic_scholar": {
        "name": "Semantic Scholar",
        "description": "Academic paper discovery with open-access PDF links",
        "registration_url": "https://www.semanticscholar.org/product/api#api-key-form",
        "registration_note": "Register with name, email, affiliation, use-case. Reviewed manually.",
    },
    "huggingface": {
        "name": "HuggingFace",
        "description": "Datasets (Wikipedia, OSCAR, etc.). Optional token for gated datasets.",
        "registration_url": "https://huggingface.co/join",
        "registration_note": "Optional. Register with email + password. Token from Settings → Access Tokens.",
    },
}


@router.get("/open-access/sources")
async def list_sources() -> dict:
    """List all available open-access sources with their key status."""
    sources = []
    for source_id, info in SOURCE_INFO.items():
        sources.append({
            "id": source_id,
            "name": info["name"],
            "description": info["description"],
            "registration_url": info["registration_url"],
            "registration_note": info["registration_note"],
            "has_key": bool(_get_key(source_id)),
            "needs_key": source_id in ("core", "pmc", "openalex", "semantic_scholar", "huggingface"),
        })
    return {"sources": sources}


@router.post("/open-access/api-key")
async def set_api_key(req: SetKeyRequest) -> dict:
    """Set an API key for a source (stored in-memory, never on disk)."""
    if req.source not in SOURCE_INFO:
        raise HTTPException(400, f"Unknown source: {req.source}")
    _runtime_keys[req.source] = req.api_key.strip()
    log.info("api_key_set", source=req.source)
    return {"ok": True, "source": req.source, "has_key": True}


@router.delete("/open-access/api-key/{source}")
async def delete_api_key(source: str) -> dict:
    """Remove a stored API key."""
    if source not in SOURCE_INFO:
        raise HTTPException(400, f"Unknown source: {source}")
    _runtime_keys.pop(source, None)
    return {"ok": True, "source": source, "has_key": bool(_get_key(source))}


# --------------------------------------------------------------------------- #
# Search endpoints (per source)
# --------------------------------------------------------------------------- #


class SearchRequest(BaseModel):
    source: str
    query: str
    limit: int = 20
    language: str | None = None


@router.post("/open-access/search")
async def search_sources(req: SearchRequest) -> dict:
    """Search an open-access source for full-text content."""
    if req.source == "core":
        return await _search_core(req.query, req.limit)
    elif req.source == "pmc":
        return await _search_pmc(req.query, req.limit)
    elif req.source == "arxiv":
        return await _search_arxiv(req.query, req.limit)
    elif req.source == "leipzig":
        return await _search_leipzig(req.query, req.limit, req.language or "eng")
    elif req.source == "zenodo":
        return await _search_zenodo(req.query, req.limit)
    elif req.source == "openalex":
        return await _search_openalex(req.query, req.limit)
    elif req.source == "semantic_scholar":
        return await _search_s2(req.query, req.limit)
    else:
        raise HTTPException(400, f"Search not supported for source: {req.source}")


# --------------------------------------------------------------------------- #
# Download endpoint
# --------------------------------------------------------------------------- #


class DownloadRequest(BaseModel):
    source: str
    item_id: str
    title: str = ""


@router.post("/open-access/download")
async def download_item(req: DownloadRequest) -> dict:
    """Download a single item's full text. Returns the text content.

    The frontend receives the text and saves it to disk via the browser's
    download mechanism.
    """

    if req.source == "core":
        text = await _download_core(req.item_id)
    elif req.source == "pmc":
        text = await _download_pmc(req.item_id)
    elif req.source == "arxiv":
        text = await _download_arxiv(req.item_id)
    elif req.source == "leipzig":
        text = await _download_leipzig(req.item_id, req.title)
    elif req.source == "zenodo":
        text = await _download_zenodo(req.item_id)
    elif req.source == "openalex":
        text = await _download_openalex(req.item_id)
    elif req.source == "semantic_scholar":
        # S2 doesn't host full text — return the OA PDF URL
        url = await _get_s2_pdf_url(req.item_id)
        return {"type": "url", "url": url, "title": req.title}
    else:
        raise HTTPException(400, f"Download not supported for source: {req.source}")

    # Return as downloadable text file
    safe_title = re.sub(r"[^\w\- ]", "_", req.title or req.item_id)[:80].strip() or "corpus_text"
    fname = f"{safe_title}.txt"
    return {
        "type": "text",
        "filename": fname,
        "content": text,
        "size": len(text.encode("utf-8")),
    }


# --------------------------------------------------------------------------- #
# CORE (core.ac.uk)
# --------------------------------------------------------------------------- #


async def _search_core(query: str, limit: int) -> dict:
    key = _get_key("core")
    if not key:
        raise HTTPException(403, "CORE API key required. Register at https://core.ac.uk/services/api")
    url = "https://api.core.ac.uk/v3/search/outputs/"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    params = {"q": query, "limit": min(limit, 100)}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                return {"results": [], "error": f"CORE API returned {r.status_code}"}
            data = r.json()
            results = []
            for item in data.get("results", []):
                results.append({
                    "id": str(item.get("id", "")),
                    "title": item.get("title", "Untitled"),
                    "authors": item.get("authors", [])[:3] if isinstance(item.get("authors"), list) else [],
                    "year": item.get("year_published"),
                    "has_full_text": bool(item.get("fullText")),
                    "source": "core",
                    "download_url": None,
                })
            return {"results": results[:limit], "total": data.get("total", len(results))}
    except httpx.HTTPError as e:
        return {"results": [], "error": str(e)}


async def _download_core(item_id: str) -> str:
    key = _get_key("core")
    if not key:
        raise HTTPException(403, "CORE API key required")
    url = f"https://api.core.ac.uk/v3/outputs/{item_id}"
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, f"CORE returned {r.status_code}")
        data = r.json()
        full_text = data.get("fullText", "")
        if not full_text:
            raise HTTPException(404, "Full text not available for this item")
        # Clean up: remove excessive whitespace
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        return full_text


# --------------------------------------------------------------------------- #
# PMC (PubMed Central)
# --------------------------------------------------------------------------- #


async def _search_pmc(query: str, limit: int) -> dict:
    key = _get_key("pmc")
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    headers = {}
    params = {"db": "pmc", "term": query, "retmax": min(limit, 50), "retmode": "json"}
    if key:
        params["api_key"] = key
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: search
            r = await client.get(f"{base}/esearch.fcgi", headers=headers, params=params)
            if r.status_code != 200:
                return {"results": [], "error": f"PMC search returned {r.status_code}"}
            data = r.json()
            ids = data.get("esearchresult", {}).get("idlist", [])
            if not ids:
                return {"results": [], "total": 0}

            # Step 2: summarize
            sum_params = {"db": "pmc", "id": ",".join(ids), "retmode": "json"}
            if key:
                sum_params["api_key"] = key
            r2 = await client.get(f"{base}/esummary.fcgi", params=sum_params)
            results = []
            if r2.status_code == 200:
                sum_data = r2.json().get("result", {})
                for pmc_id in ids:
                    item = sum_data.get(pmc_id, {})
                    results.append({
                        "id": pmc_id,
                        "title": item.get("title", "Untitled"),
                        "authors": [a.get("name", "") for a in item.get("authors", [])[:3]],
                        "year": item.get("pubdate", "")[:4] if item.get("pubdate") else None,
                        "has_full_text": True,
                        "source": "pmc",
                        "download_url": None,
                    })
            return {"results": results[:limit], "total": len(ids)}
    except httpx.HTTPError as e:
        return {"results": [], "error": str(e)}


async def _download_pmc(item_id: str) -> str:
    key = _get_key("pmc")
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    params = {"db": "pmc", "id": item_id, "rettype": "full", "retmode": "xml"}
    if key:
        params["api_key"] = key
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{base}/efetch.fcgi", params=params)
        if r.status_code != 200:
            raise HTTPException(502, f"PMC fetch returned {r.status_code}")
        # Parse JATS XML and extract text
        try:
            root = ET.fromstring(r.text)
            texts = []
            for elem in root.iter():
                if elem.tag.endswith("p") and elem.text:
                    texts.append(elem.text.strip())
            full_text = "\n\n".join(texts)
            if not full_text:
                # Fallback: return raw text stripped of tags
                full_text = re.sub(r"<[^>]+>", " ", r.text)
                full_text = re.sub(r"\s+", " ", full_text).strip()
            return full_text
        except ET.ParseError:
            # Return raw text if XML parsing fails
            return re.sub(r"<[^>]+>", " ", r.text).strip()[:50000]


# --------------------------------------------------------------------------- #
# arXiv
# --------------------------------------------------------------------------- #


async def _search_arxiv(query: str, limit: int) -> dict:
    url = "http://export.arxiv.org/api/query"
    params = {"search_query": f"all:{query}", "max_results": min(limit, 50), "sortBy": "relevance"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return {"results": [], "error": f"arXiv returned {r.status_code}"}
            # Parse Atom XML
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            try:
                root = ET.fromstring(r.text)
                results = []
                for entry in root.findall("atom:entry", ns):
                    arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
                    title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
                    entry.find("atom:summary", ns).text.strip()[:200] if entry.find("atom:summary", ns) is not None else ""
                    published = entry.find("atom:published", ns).text[:4] if entry.find("atom:published", ns) is not None else ""
                    authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)][:3]
                    results.append({
                        "id": arxiv_id,
                        "title": title,
                        "authors": authors,
                        "year": published,
                        "has_full_text": True,
                        "source": "arxiv",
                        "download_url": f"https://arxiv.org/pdf/{arxiv_id}",
                    })
                return {"results": results[:limit], "total": len(results)}
            except ET.ParseError:
                return {"results": [], "error": "Failed to parse arXiv response"}
    except httpx.HTTPError as e:
        return {"results": [], "error": str(e)}


async def _download_arxiv(item_id: str) -> str:
    """Download arXiv abstract + full text (as plain text from the PDF page).

    Note: arXiv full text is PDF-only. We download the abstract page
    and return it as text. For full PDF download, the frontend gets
    the download_url from search and can fetch the PDF directly.
    """
    url = f"https://export.arxiv.org/api/query?id_list={item_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(502, f"arXiv returned {r.status_code}")
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(r.text)
            entry = root.find("atom:entry", ns)
            if entry is None:
                raise HTTPException(404, "arXiv article not found")
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            summary = entry.find("atom:summary", ns).text.strip() if entry.find("atom:summary", ns) is not None else ""
            return f"# {title}\n\narXiv: {item_id}\n\n## Abstract\n\n{summary}\n\n## Full text\n\nDownload PDF: https://arxiv.org/pdf/{item_id}"
        except ET.ParseError:
            raise HTTPException(502, "Failed to parse arXiv response") from None


# --------------------------------------------------------------------------- #
# Leipzig Corpora
# --------------------------------------------------------------------------- #


LEIPZIG_LANG_MAP = {
    "en": "eng", "ar": "ara", "fr": "fra", "de": "deu", "es": "spa",
    "zh": "zho", "ja": "jpn", "ru": "rus", "pt": "por", "it": "ita",
}


async def _search_leipzig(query: str, limit: int, language: str) -> dict:
    """List available Leipzig corpora for a language."""
    lang_code = LEIPZIG_LANG_MAP.get(language, language)
    url = f"https://downloads.wortschatz-leipzig.de/corpora/list/{lang_code}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                # Fallback: return curated list
                return {
                    "results": [
                        {
                            "id": f"{lang_code}_newscrawl_2013_1M",
                            "title": f"Leipzig News Crawl 2013 ({language}) — 1M sentences",
                            "has_full_text": True,
                            "source": "leipzig",
                            "download_url": f"https://downloads.wortschatz-leipzig.de/corpora/{lang_code}_newscrawl_2013_1M.tar.gz",
                            "size": "~20 MB",
                        },
                        {
                            "id": f"{lang_code}_newscrawl_2019_1M",
                            "title": f"Leipzig News Crawl 2019 ({language}) — 1M sentences",
                            "has_full_text": True,
                            "source": "leipzig",
                            "download_url": f"https://downloads.wortschatz-leipzig.de/corpora/{lang_code}_newscrawl_2019_1M.tar.gz",
                            "size": "~20 MB",
                        },
                    ],
                    "total": 2,
                }
            data = r.json()
            results = []
            for corpus in data[:limit]:
                results.append({
                    "id": corpus.get("corpusName", corpus.get("id", "")),
                    "title": corpus.get("corpusName", "Leipzig Corpus"),
                    "has_full_text": True,
                    "source": "leipzig",
                    "download_url": f"https://downloads.wortschatz-leipzig.de/corpora/{corpus.get('corpusName', '')}.tar.gz",
                    "size": corpus.get("size", "unknown"),
                })
            return {"results": results, "total": len(results)}
    except httpx.HTTPError:
        # Fallback for network errors
        return {
            "results": [
                {
                    "id": f"{lang_code}_newscrawl_2013_1M",
                    "title": f"Leipzig News Crawl 2013 ({language}) — 1M sentences",
                    "has_full_text": True,
                    "source": "leipzig",
                    "download_url": f"https://downloads.wortschatz-leipzig.de/corpora/{lang_code}_newscrawl_2013_1M.tar.gz",
                    "size": "~20 MB",
                },
            ],
            "total": 1,
        }


async def _download_leipzig(item_id: str, title: str) -> str:
    """Leipzig corpora are bulk tar.gz downloads — return the download URL.

    The frontend will download the tar.gz directly and the user can
    extract + upload the .txt files into a corpus.
    """
    # We can't easily extract tar.gz in the browser, so return the URL
    # for direct download
    raise HTTPException(200, detail="Use download_url for Leipzig corpora (tar.gz bulk download)") from None


# --------------------------------------------------------------------------- #
# Zenodo
# --------------------------------------------------------------------------- #


async def _search_zenodo(query: str, limit: int) -> dict:
    url = "https://zenodo.org/api/records"
    params = {"q": query, "size": min(limit, 50), "sort": "bestmatch"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return {"results": [], "error": f"Zenodo returned {r.status_code}"}
            data = r.json()
            results = []
            for hit in data.get("hits", {}).get("hits", []):
                files = hit.get("files", [])
                has_text = any(f.get("key", "").endswith((".txt", ".csv", ".tsv", ".xml")) for f in files)
                results.append({
                    "id": str(hit.get("id", "")),
                    "title": hit.get("metadata", {}).get("title", "Untitled"),
                    "authors": [c.get("name", "") for c in hit.get("metadata", {}).get("creators", [])[:3]],
                    "year": hit.get("metadata", {}).get("publication_date", "")[:4] if hit.get("metadata", {}).get("publication_date") else None,
                    "has_full_text": has_text or len(files) > 0,
                    "source": "zenodo",
                    "download_url": hit.get("links", {}).get("latest_html", ""),
                    "files": [{"name": f.get("key", ""), "size": f.get("size", 0)} for f in files[:5]],
                })
            return {"results": results[:limit], "total": data.get("hits", {}).get("total", 0)}
    except httpx.HTTPError as e:
        return {"results": [], "error": str(e)}


async def _download_zenodo(item_id: str) -> str:
    """Download the first text file from a Zenodo record."""
    url = f"https://zenodo.org/api/records/{item_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                raise HTTPException(502, f"Zenodo returned {r.status_code}")
            data = r.json()
            files = data.get("files", [])
            # Find first text file
            for f in files:
                fname = f.get("key", "")
                if fname.endswith((".txt", ".csv", ".tsv")):
                    file_url = f.get("links", {}).get("self", "")
                    if file_url:
                        r2 = await client.get(file_url)
                        if r2.status_code == 200:
                            return r2.text[:500000]  # Cap at 500KB
            # No text file — return metadata
            title = data.get("metadata", {}).get("title", "Untitled")
            return f"# {title}\n\nZenodo record: {item_id}\n\nNo downloadable text file found. Visit https://zenodo.org/records/{item_id} for files."
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Zenodo download failed: {e}") from e


# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #


async def _search_openalex(query: str, limit: int) -> dict:
    key = _get_key("openalex")
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": min(limit, 50)}
    headers = {}
    if key:
        params["api_key"] = key
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code != 200:
                return {"results": [], "error": f"OpenAlex returned {r.status_code}"}
            data = r.json()
            results = []
            for work in data.get("results", []):
                oa_url = work.get("open_access", {}).get("oa_url")
                results.append({
                    "id": work.get("id", "").split("/")[-1],
                    "title": work.get("title", "Untitled"),
                    "authors": [a.get("author", {}).get("display_name", "") for a in work.get("authorships", [])[:3]],
                    "year": work.get("publication_year"),
                    "has_full_text": work.get("open_access", {}).get("is_oa", False),
                    "source": "openalex",
                    "download_url": oa_url,
                })
            return {"results": results[:limit], "total": data.get("meta", {}).get("count", 0)}
    except httpx.HTTPError as e:
        return {"results": [], "error": str(e)}


async def _download_openalex(item_id: str) -> str:
    """OpenAlex doesn't host full text directly — return the OA URL."""
    key = _get_key("openalex")
    url = f"https://api.openalex.org/works/{item_id}"
    params = {}
    if key:
        params["api_key"] = key
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            raise HTTPException(502, f"OpenAlex returned {r.status_code}")
        data = r.json()
        oa_url = data.get("open_access", {}).get("oa_url")
        title = data.get("title", "Untitled")
        abstract_idx = data.get("abstract_inverted_index", {})
        # Reconstruct abstract from inverted index
        abstract_words = []
        if abstract_idx:
            max_pos = max(max(positions) for positions in abstract_idx.values()) if abstract_idx else 0
            abstract_words = [""] * (max_pos + 1)
            for word, positions in abstract_idx.items():
                for pos in positions:
                    if pos < len(abstract_words):
                        abstract_words[pos] = word
        abstract = " ".join(abstract_words)
        return f"# {title}\n\nOpenAlex: {item_id}\n\n## Abstract\n\n{abstract}\n\n## Full text\n\nOpen access URL: {oa_url or 'Not available'}"


# --------------------------------------------------------------------------- #
# Semantic Scholar
# --------------------------------------------------------------------------- #


async def _search_s2(query: str, limit: int) -> dict:
    key = _get_key("semantic_scholar")
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": query, "limit": min(limit, 50), "fields": "title,authors,year,openAccessPdf,abstract"}
    headers = {}
    if key:
        headers["x-api-key"] = key
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code != 200:
                return {"results": [], "error": f"Semantic Scholar returned {r.status_code}"}
            data = r.json()
            results = []
            for paper in data.get("data", []):
                pdf_url = paper.get("openAccessPdf", {}).get("url") if paper.get("openAccessPdf") else None
                results.append({
                    "id": paper.get("paperId", ""),
                    "title": paper.get("title", "Untitled"),
                    "authors": [a.get("name", "") for a in paper.get("authors", [])[:3]],
                    "year": paper.get("year"),
                    "has_full_text": bool(pdf_url),
                    "source": "semantic_scholar",
                    "download_url": pdf_url,
                })
            return {"results": results[:limit], "total": data.get("total", 0)}
    except httpx.HTTPError as e:
        return {"results": [], "error": str(e)}


async def _get_s2_pdf_url(item_id: str) -> str:
    key = _get_key("semantic_scholar")
    url = f"https://api.semanticscholar.org/graph/v1/paper/{item_id}"
    params = {"fields": "openAccessPdf,title"}
    headers = {}
    if key:
        headers["x-api-key"] = key
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params, headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, f"Semantic Scholar returned {r.status_code}")
        data = r.json()
        pdf_url = data.get("openAccessPdf", {}).get("url") if data.get("openAccessPdf") else None
        if not pdf_url:
            raise HTTPException(404, "No open-access PDF available for this paper")
        return pdf_url

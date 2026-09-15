"""Hugging Face GGUF catalogue explorer (v1.2.0).

Ported from CorpusMind Lens (catalog.py, v0.3.2) and adapted for the main
engine. Lets users browse and pull GGUF models straight from Hugging Face
through the normal Ollama pull flow — ``hf.co/<user>/<repo>:<quant>`` pulls
fine through ``POST /api/v1/ollama/pull`` because Ollama resolves HF GGUF
repositories natively.

Design notes (honesty first):
- Search hits the public HF API (``/api/models?filter=gguf``) sorted by
  real download counts. No curation, no hidden ranking.
- Quant-variant sizes come from the repo's real file listing
  (``/api/models/{repo}?blobs=true``), not from filename guesses.
- Fit badges (gpu / cpu / tight / too-big) are *rule-of-thumb* estimates
  from the machine's actual RAM/VRAM against the GGUF file size plus a
  context overhead factor. They are labelled as estimates everywhere.
- Embedding-model classification is heuristic (HF pipeline_tag + name
  patterns) and reported as such.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.logging import get_logger

log = get_logger(__name__)

HUGGINGFACE_API = "https://huggingface.co/api/models"

# Preferred quantisation order shown in the variant picker (best size/quality
# trade-off first, per the Lens companion's convention).
QUANT_ORDER = [
    "Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M", "Q5_K_S", "Q6_K", "Q8_0",
    "Q3_K_M", "Q3_K_L", "Q2_K", "IQ4_XS", "IQ3_XXS", "F16", "BF16",
]

# Rough context/state overhead multiplier applied to the raw file size when
# estimating runtime memory need. Rule of thumb, not a measurement.
_RAM_OVERHEAD_FACTOR = 1.25
_RAM_OVERHEAD_ABSOLUTE = 0.5 * 1024**3  # +0.5 GB kv-cache/scratch, heuristically

# Name fragments that (heuristically) mark an embedding model.
_EMBED_NAME_HINTS = (
    "embed", "bge", "e5", "gte", "minilm", "nomic", "arctic", "jina",
    "sentence", "voyage", "m3", "st-", "gvit",
)

_EMBED_PIPELINE_TAGS = {"feature-extraction", "sentence-similarity", "embeddings"}


# --------------------------------------------------------------------------- #
# Machine profile — real RAM (stdlib per-OS) + best-effort VRAM (nvidia-smi)
# --------------------------------------------------------------------------- #


@dataclass
class MachineProfile:
    ram_total: int = 0          # bytes
    ram_available: int = 0      # bytes
    vram_total: int = 0         # bytes (0 = no discrete GPU detected)
    vram_available: int = 0
    gpu_name: str = ""
    source: str = "unknown"     # how RAM was detected (transparency)
    probe_error: str = ""


_profile_cache: MachineProfile | None = None
_profile_cached_at: float = 0.0
_PROFILE_TTL = 60.0


def _read_ram_linux() -> tuple[int, int] | None:
    try:
        text = Path_read_text("/proc/meminfo")
        vals: dict[str, int] = {}
        for line in text.splitlines():
            if ":" in line:
                key, rest = line.split(":", 1)
                nums = re.findall(r"\d+", rest)
                if nums:
                    vals[key.strip()] = int(nums[0]) * 1024  # kB → bytes
        if "MemTotal" in vals:
            return vals["MemTotal"], vals.get("MemAvailable", vals.get("MemFree", 0))
    except Exception:
        return None
    return None


def Path_read_text(path: str) -> str:  # pragma: no cover - platform helper
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_ram_macos() -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            ["sysctl", "hw.memsize"], capture_output=True, text=True, timeout=5
        )
        total = int(out.stdout.split()[-1])
        # macOS has no MemAvailable concept; report total for both.
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
        free_pages = 0
        m = re.search(r"Pages free:\s+(\d+)", vm.stdout)
        if m:
            free_pages = int(m.group(1)) * 4096
        return total, free_pages
    except Exception:
        return None


def _read_ram_windows() -> tuple[int, int] | None:  # pragma: no cover
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
    except Exception:
        return None


def _read_vram_nvidia() -> tuple[int, int, str] | None:
    """Best-effort VRAM probe via nvidia-smi (absent → no GPU info)."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        # First GPU line wins (multi-GPU: report the smallest-capacity card
        # is wrong; the largest is optimistic — take the first, honestly).
        line = out.stdout.strip().splitlines()[0]
        total_s, free_s, name = [p.strip() for p in line.split(",")]
        return int(float(total_s)) * 1024**2, int(float(free_s)) * 1024**2, name
    except Exception:
        return None


def machine_profile(*, refresh: bool = False) -> MachineProfile:
    """Detect the machine's RAM (and VRAM when an NVIDIA GPU is present)."""
    global _profile_cache, _profile_cached_at
    now = time.monotonic()
    if _profile_cache is not None and not refresh and (now - _profile_cached_at) < _PROFILE_TTL:
        return _profile_cache

    ram: tuple[int, int] | None = None
    source = "unknown"
    try:
        if sys.platform.startswith("linux"):
            ram = _read_ram_linux()
            source = "proc/meminfo"
        elif sys.platform == "darwin":
            ram = _read_ram_macos()
            source = "sysctl hw.memsize"
        elif sys.platform.startswith("win"):
            ram = _read_ram_windows()
            source = "GlobalMemoryStatusEx"
    except Exception as e:  # pragma: no cover
        log.warning("machine_ram_probe_failed", error=str(e))

    profile = MachineProfile()
    if ram:
        profile.ram_total, profile.ram_available = ram
        profile.source = source
    else:
        profile.probe_error = "could not detect system memory"

    vram = _read_vram_nvidia()
    if vram:
        profile.vram_total, profile.vram_available, profile.gpu_name = vram

    _profile_cache = profile
    _profile_cached_at = now
    return profile


# --------------------------------------------------------------------------- #
# Fit badges — explicit rule-of-thumb, computed from real file sizes
# --------------------------------------------------------------------------- #


def _memory_need(size_bytes: int) -> int:
    return int(size_bytes * _RAM_OVERHEAD_FACTOR + _RAM_OVERHEAD_ABSOLUTE)


def fit_badge(size_bytes: int, profile: MachineProfile | None = None) -> dict[str, Any]:
    """Classify a model file against the machine. Honest rule-of-thumb."""
    if profile is None:
        profile = machine_profile()
    need = _memory_need(size_bytes)
    if profile.ram_total <= 0:
        return {"fit": "unknown", "fit_note": "machine memory could not be detected"}
    if profile.vram_total and need <= profile.vram_available * 0.9:
        return {"fit": "gpu", "fit_note": f"likely fits on GPU ({_fmt_size(profile.vram_total)} VRAM)"}
    if need <= profile.ram_available * 0.8:
        return {"fit": "cpu", "fit_note": f"fits comfortably in available RAM ({_fmt_size(profile.ram_available)})"}
    if need <= profile.ram_total * 0.9:
        return {"fit": "tight", "fit_note": f"may run, but RAM is tight (total {_fmt_size(profile.ram_total)})"}
    return {"fit": "too-big", "fit_note": f"larger than this machine's memory ({_fmt_size(profile.ram_total)} RAM)"}


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B",) else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"  # pragma: no cover


_QUANT_RE = re.compile(r"\b(I?Q\d(?:_K(?:_S|M|L|XL|XXS)?)?|Q\d_\d|F16|BF16|F32)\b", re.IGNORECASE)


def _quant_of(filename: str) -> str | None:
    m = _QUANT_RE.search(filename)
    if not m:
        return None
    q = m.group(1).upper()
    return q if q in {x.upper() for x in QUANT_ORDER} or q.startswith(("Q", "IQ")) else None


def classify_task(repo_id: str, pipeline_tag: str | None, tags: list[str]) -> str:
    """Heuristic text-vs-embedding classification (reported as heuristic)."""
    name = repo_id.lower()
    if pipeline_tag in _EMBED_PIPELINE_TAGS:
        return "embedding"
    if any(h in name for h in _EMBED_NAME_HINTS):
        return "embedding"
    if "text-generation" in (tags or []):
        return "text"
    return "text"


# --------------------------------------------------------------------------- #
# HF search — live, sorted by downloads, quant variants from real blobs
# --------------------------------------------------------------------------- #

_search_cache: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_TTL = 300.0  # 5 minutes
_DETAIL_CONCURRENCY = 6


async def search_gguf(
    query: str,
    *,
    task: str = "any",
    limit: int = 20,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Search Hugging Face for GGUF models matching *query*.

    Returns {"models": [...], "machine": {...}, "note": "..."}.
    Results are sorted by downloads (the API does the sorting) and the top
    repos are enriched with real per-quant file sizes (blobs=true).
    """
    query = (query or "").strip()
    if not query:
        return {"models": [], "note": "Type a search query to browse Hugging Face.", "machine": _machine_dict()}

    cache_key = f"{query.lower()}|{task}|{limit}"
    cached = _search_cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _SEARCH_TTL:
        return {"models": cached[1], "note": _RESULT_NOTE, "machine": _machine_dict(), "cached": True}

    params = {
        "search": query,
        "filter": "gguf",
        "sort": "downloads",
        "direction": -1,
        "limit": min(max(limit * 2, 20), 60),
    }
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        r = await client.get(HUGGINGFACE_API, params=params)
        r.raise_for_status()
        results = r.json()

    profile = machine_profile()
    models: list[dict] = []
    kept = 0
    sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

    async def enrich(repo_id: str) -> dict | None:
        try:
            async with sem:
                detail_r = await client.get(
                    f"{HUGGINGFACE_API}/{repo_id}", params={"blobs": "true"}
                )
                detail_r.raise_for_status()
                detail = detail_r.json()
        except Exception as e:  # repo vanished / rate limited — skip, honestly
            log.info("hf_detail_fetch_skipped", repo=repo_id, error=str(e))
            return None
        siblings = detail.get("siblings") or []
        variants: list[dict] = []
        for sib in siblings:
            fname = sib.get("rfilename", "")
            if not fname.lower().endswith(".gguf"):
                continue
            size = sib.get("size") or 0
            quant = _quant_of(fname)
            if not size:
                # blobs=true should give sizes; fall back to 0 and skip badge
                fit = {"fit": "unknown", "fit_note": "size metadata unavailable"}
            else:
                fit = fit_badge(int(size), profile)
            variants.append({
                "quant": quant or "",
                "filename": fname,
                "size_bytes": int(size),
                "size": _fmt_size(size) if size else "",
                "pull_name": f"hf.co/{repo_id}:{quant or 'latest'}",
                **fit,
            })
        if not variants:
            return None
        # Preferred order first, then by size ascending.
        def vkey(v: dict) -> tuple[int, int]:
            q = (v["quant"] or "").upper()
            order = QUANT_ORDER + [q for q in [v["quant"]] if q not in QUANT_ORDER]
            rank = order.index(q) if q in order else len(order)
            return (rank, v["size_bytes"])
        variants.sort(key=vkey)
        tag_list = detail.get("tags") or []
        ptag = detail.get("pipeline_tag")
        return {
            "repo": repo_id,
            "model": repo_id.split("/")[-1],
            "author": repo_id.split("/")[0] if "/" in repo_id else "",
            "downloads": detail.get("downloads", 0),
            "likes": detail.get("likes", 0),
            "pipeline_tag": ptag or "",
            "task": classify_task(repo_id, ptag, tag_list),
            "last_modified": (detail.get("lastModified") or "")[:10],
            "quant_variants": variants,
            "default_pull": variants[0]["pull_name"],
            "best_size": variants[0]["size"],
            "rule_of_thumb": True,
        }

    for item in results:
        if kept >= limit:
            break
        repo_id = item.get("modelId") or item.get("id") or ""
        if not repo_id:
            continue
        item_task = classify_task(
            repo_id, item.get("pipeline_tag"), item.get("tags") or []
        )
        if task in ("text", "embedding") and item_task != task:
            continue
        enriched = await enrich(repo_id)
        if enriched is None:
            continue
        models.append(enriched)
        kept += 1

    _search_cache[cache_key] = (time.monotonic(), models)
    return {"models": models, "note": _RESULT_NOTE, "machine": _machine_dict()}


_RESULT_NOTE = (
    "Live Hugging Face results sorted by downloads. Sizes are the real GGUF "
    "file sizes; fit badges are rule-of-thumb estimates from this machine's "
    "RAM/VRAM, not guarantees."
)


def _machine_dict() -> dict[str, Any]:
    p = machine_profile()
    return {
        "ram_total": p.ram_total,
        "ram_available": p.ram_available,
        "vram_total": p.vram_total,
        "vram_available": p.vram_available,
        "gpu_name": p.gpu_name,
        "ram_total_human": _fmt_size(p.ram_total) if p.ram_total else "",
        "ram_available_human": _fmt_size(p.ram_available) if p.ram_available else "",
        "vram_total_human": _fmt_size(p.vram_total) if p.vram_total else "",
        "source": p.source,
    }

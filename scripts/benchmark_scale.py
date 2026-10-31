"""Benchmark: CorpusMind corpus pipeline at scale (1M / 10M tokens) — A7.

Measures wall time and peak RSS of three PRODUCTION paths on synthetic
English corpora of 1M and 10M tokens:

  1. ingest  — ingestion.service.ingest_document (parse_file -> spaCy
               pipeline -> Token rows in SQLite), the same function the
               corpus-management API calls.
  2. KWIC    — stats.service.search_concordance (SQL-backed concordance),
               word level, window 5.
  3. keyness — stats.service.compute_keyness (target vs reference corpus,
               log-likelihood + effect size).

Corpus construction (documented, by design — same pattern as
scripts/benchmark_arabic_corpus.py): the fixed sentence pool below is built
from the engine's own hash-frozen English snapshot texts
(engine/eval/data/snapshot/en_*.txt), split into sentences deterministically;
the pool is then cycled with light numeric variation to build documents of
~1000 tokens until the target token count is reached. The corpus is
therefore REPETITIVE (small vocabulary): tok/s reflects steady-state
storage-path throughput on repetitive text, and keyness operates on a small
type inventory. `_meta` records pool provenance, vocabulary size, document
count and the exact token count of every measured corpus so readers can
judge this.

Peak RSS is the process-wide monotone maximum (resource.getrusage
RUSAGE_SELF ru_maxrss, KiB on Linux), snapshotted after each phase — the
per-phase value is "peak so far", not a per-phase increment.

Run (CI):
    CORPUSMIND_DB_URL=sqlite+aiosqlite:////tmp/scale/scale.db \
    python scripts/benchmark_scale.py --sizes 1000000 --out benchmarks/out
Env:
    CORPUSMIND_SCALE_SIZES=1000000,10000000  (--sizes fallback)

The database URL MUST be provided via CORPUSMIND_DB_URL (the script refuses
to run against the default ~/.corpusmind data dir); each size run should use
its own fresh file so ingest cost includes table creation and cannot reuse a
previous size's rows.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import platform
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "engine"))

# ---------------------------------------------------------------------------
# Sentence pool: the engine's frozen English snapshot texts, split into
# sentences. Deterministic: files sorted by name, regex sentence split,
# sentences kept only if 6..40 whitespace tokens (drops headings/fragments).
# ---------------------------------------------------------------------------

SNAPSHOT_DIR = REPO_ROOT / "engine" / "eval" / "data" / "snapshot"
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
DOC_TOKENS = 1000          # target tokens per document
REF_TOKENS = 50_000        # reference-corpus size (keyness side B)
COMMIT_EVERY = 50          # docs per commit during ingest

_pool_cache: list[str] | None = None


def load_pool() -> list[str]:
    global _pool_cache
    if _pool_cache is not None:
        return _pool_cache
    sentences: list[str] = []
    for p in sorted(SNAPSHOT_DIR.glob("en_*.txt")):
        text = p.read_text(encoding="utf-8")
        for s in SENT_SPLIT.split(text):
            s = s.strip()
            n = len(s.split())
            if 6 <= n <= 40:
                sentences.append(s)
    _pool_cache = sentences
    return sentences


def build_docs(target_tokens: int) -> tuple[list[str], int]:
    """Cycle the sentence pool into ~DOC_TOKENS-token documents until the
    corpus holds >= target_tokens whitespace tokens. Returns (docs, tokens)."""
    pool = load_pool()
    docs: list[str] = []
    total = 0
    i = 0
    while total < target_tokens:
        buf: list[str] = []
        n = 0
        while n < DOC_TOKENS:
            s = pool[i % len(pool)]
            i += 1
            buf.append(s)
            n += len(s.split())
        docs.append(" ".join(buf))
        total += n
    return docs, total


def peak_rss_kib() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def phase_meta() -> dict:
    return {"peak_rss_kib": peak_rss_kib()}


async def run_size(size: int, out_dir: Path, db_url: str) -> dict:
    os.environ["CORPUSMIND_DB_URL"] = db_url
    for mod in ["app.settings", "storage.session", "ingestion.service",
                "stats.service"]:
        sys.modules.pop(mod, None)  # drop cached settings/engine from prior size

    from app.settings import get_settings
    from storage.models import Corpus, Project
    from storage.session import init_db, dispose_db, get_session  # noqa: F401
    from ingestion.service import ingest_document
    from stats.service import search_concordance, compute_keyness

    report: dict = {"size_tokens_target": size}
    tmp = Path(tempfile.mkdtemp(prefix=f"scalebench-{size}-"))

    docs, total_tokens = build_docs(size)
    ref_docs, ref_total = build_docs(REF_TOKENS)
    pool = load_pool()
    vocab = len({w for s in pool for w in s.split()})
    report["corpus"] = {
        "pattern": "cycled fixed snapshot sentences (en_*.txt), ~1000 tok/doc",
        "pool_sentences": len(pool),
        "pool_vocab_types": vocab,
        "documents": len(docs),
        "actual_tokens": total_tokens,
        "reference_documents": len(ref_docs),
        "reference_tokens": ref_total,
        "unique_input_tokens": vocab,
    }

    # --- ingest ------------------------------------------------------------
    t0 = time.perf_counter()
    await init_db()
    async for session in get_session():
        project = Project(name=f"scale-{size}")
        session.add(project)
        await session.flush()
        target = Corpus(project_id=project.id, name="target", language="en")
        reference = Corpus(project_id=project.id, name="reference", language="en")
        session.add_all([target, reference])
        await session.flush()

        n_docs = 0
        for idx, text in enumerate(docs):
            await ingest_document(session, target, f"scale_{idx:06d}.txt",
                                  text.encode("utf-8"), language="en")
            n_docs += 1
            if n_docs % COMMIT_EVERY == 0:
                await session.commit()
        for idx, text in enumerate(ref_docs):
            await ingest_document(session, reference, f"ref_{idx:06d}.txt",
                                  text.encode("utf-8"), language="en")
        await session.commit()
        report["ingest"] = {
            "wall_s": round(time.perf_counter() - t0, 2),
            "tokens": total_tokens + ref_total,
            "tokens_per_s": round((total_tokens + ref_total)
                                  / (time.perf_counter() - t0), 1),
            "pipeline": _pipeline_info(),
            **phase_meta(),
        }
    await dispose_db()
    gc.collect()

    # --- KWIC (concordance) -------------------------------------------------
    # second query: deterministic mid-frequency pool word (4th most common
    # type after skipping the top 3) so both KWIC queries exercise the scan.
    from collections import Counter
    pool_freq = Counter(w for s in load_pool() for w in s.lower().split())
    second_word = [w for w, _ in pool_freq.most_common(8)][3]
    await init_db()
    async for session in get_session():
        t1 = time.perf_counter()
        kwic = await search_concordance(session, target.id, "the", level="word",
                                        window=5, limit=1000)
        kwic_s = time.perf_counter() - t1
        t2 = time.perf_counter()
        kwic2 = await search_concordance(session, target.id, second_word,
                                         level="word", window=5, limit=1000)
        kwic2_s = time.perf_counter() - t2
        report["kwic"] = {
            "queries": [
                {"query": "the", "wall_s": round(kwic_s, 3),
                 "lines": kwic.total},
                {"query": second_word, "wall_s": round(kwic2_s, 3),
                 "lines": kwic2.total},
            ],
            **phase_meta(),
        }
    await dispose_db()
    gc.collect()

    # --- keyness -------------------------------------------------------------
    async for session in get_session():
        t3 = time.perf_counter()
        kr = await compute_keyness(session, target.id, reference.id,
                                   min_freq=5, limit=100)
        keyness_s = time.perf_counter() - t3
        pos = kr.positive_keywords or []
        report["keyness"] = {
            "wall_s": round(keyness_s, 3),
            "n_positive": len(pos),
            "n_negative": len(kr.negative_keywords or []),
            "top3": [row.get("term") for row in pos[:3]],
            **phase_meta(),
        }
    await dispose_db()

    db_path = db_url.split("///")[-1]
    report["db"] = {"file": db_path,
                    "size_bytes": os.path.getsize(db_path)}
    return report


def _pipeline_info() -> dict:
    from nlp.general.pipeline import get_pipeline
    info = get_pipeline(backend="spacy", language="en").info()
    return {"backend": info.backend, "model": info.model_name,
            "model_version": info.model_version,
            "spacy_version": info.spacy_version, "degraded": info.degraded}


def main() -> None:
    ap = argparse.ArgumentParser(description="A7 scale benchmark (ingest/KWIC/keyness)")
    ap.add_argument("--sizes",
                    default=os.environ.get("CORPUSMIND_SCALE_SIZES", "1000000"))
    ap.add_argument("--out", default=str(REPO_ROOT / "benchmarks" / "out"))
    args = ap.parse_args()

    db_url = os.environ.get("CORPUSMIND_DB_URL", "")
    if not db_url or ".corpusmind" in db_url:
        raise SystemExit("refusing to run: set CORPUSMIND_DB_URL to a fresh "
                         "sqlite+aiosqlite:/// path (not the default data dir)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes = [int(s) for s in str(args.sizes).split(",") if s.strip()]

    all_reports = []
    for size in sizes:
        db_url_i = db_url.replace(".db", f"-{size}.db")
        rep = asyncio.run(run_size(size, out_dir, db_url_i))
        rep["_meta"] = _meta_block(size, args)
        path = out_dir / f"scale_{size}.json"
        path.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        all_reports.append(rep)
        ing = rep["ingest"]
        print(f"[{size:>9}] ingest {ing['wall_s']} s ({ing['tokens_per_s']} tok/s, "
              f"degraded={ing['pipeline']['degraded']}) | "
              f"kwic {[q['wall_s'] for q in rep['kwic']['queries']]} s | "
              f"keyness {rep['keyness']['wall_s']} s | "
              f"peak RSS {max(ing['peak_rss_kib'], rep['kwic']['peak_rss_kib'], rep['keyness']['peak_rss_kib'])/1024:.0f} MiB",
              flush=True)

    summary = out_dir / "scale_summary.json"
    summary.write_text(json.dumps(all_reports, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"summary: {summary}")


def _meta_block(size: int, args) -> dict:
    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", *a], cwd=REPO_ROOT, capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {
        "utc": datetime.now(UTC).isoformat(),
        "commit": git("rev-parse", "HEAD"),
        "runner": {"platform": platform.platform(), "python": platform.python_version(),
                   "machine": platform.machine(),
                   "cpus": os.cpu_count()},
        "command": f"python scripts/benchmark_scale.py --sizes {args.sizes}",
        "corpus_construction": (
            "synthetic: fixed English snapshot sentences "
            "(engine/eval/data/snapshot/en_*.txt) cycled to target size; "
            "repetitive text, small vocabulary — see module docstring"),
        "rss_definition": "process-wide monotone peak (ru_maxrss), KiB",
    }


if __name__ == "__main__":
    main()

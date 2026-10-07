"""Bulk Arabic analysis job: chunking + progress + cancel (v1.2.11 follow-up).

Why this exists (measured, scripts/benchmark_arabic_corpus.py, 2026-10-07,
dev reference machine, warm cache): the calima-msa-r13 morphology analyzer
runs at ~3,950 tokens/s. That puts 100K tokens at ~25s, 500K at ~126s and
1M tokens at ~253s - far beyond the interactive request deadline
(CORPUSMIND_ARABIC_TIMEOUT_S, default 30s, sized for panel-sized texts plus
a cold DB load). Dialect ID is a different beast (1M tokens ≈ 9s) and needs
none of this.

Design:
  - POST /arabic/analyze/job rejects nothing on size: it accepts what the
    interactive route refuses (the route answers 413 above
    CORPUSMIND_ARABIC_INLINE_MAX_TOKENS with a pointer here).
  - Text is split into sentence chunks (split_arabic_sentences), each chunk
    is analyzed through the SAME analyze_arabic entry point the interactive
    route uses, so results are identical modulo aggregation.
  - Progress: tokens_done / tokens_total, chunks_done / chunks_total, ETA.
  - Cancel: cooperative, checked between chunks.
  - Result: aggregated (frequency tables), NOT a 1M-row token dump. Written
    to a temp file; GET /arabic/analyze/job/result streams it.
  - ONE bulk job at a time (second POST -> 409). Bulk work deliberately
    does NOT take the interactive concurrency slot (app/arabic_concurrency):
    a 4-minute bulk job must not make every panel request answer 429. It
    still competes for CPU; the docs say so.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from app.logging import get_logger
from nlp.arabic.pipeline import (
    ArabicDataMissingError,
    analyze_arabic,
    split_arabic_sentences,
)

log = get_logger(__name__)

# Target chunk size in tokens: small enough for responsive progress,
# large enough that per-chunk overhead is invisible (~2k tokens ≈ 0.5s).
CHUNK_TOKENS = 2_000
# Bound the aggregated tables so a 1M-token job still yields a ~10s JSON,
# not a 400MB one.
TOP_TABLE_LIMIT = 10_000
# Hard ceiling on bulk job runtime (safety net, not the usual exit).
BULK_MAX_S = float(__import__("os").environ.get("CORPUSMIND_ARABIC_BULK_MAX_S", "3600"))


class BulkBusyError(RuntimeError):
    """A bulk job is already running (HTTP 409)."""


class _JobCancelledError(Exception):
    pass


def _chunk_text(text: str) -> list[list[str]]:
    """Split text into chunks of ~CHUNK_TOKENS tokens each.

    Sentence-based first (split_arabic_sentences), but a single unpunctuated
    run longer than CHUNK_TOKENS (real corpora contain them) is further cut
    into word windows, so progress granularity and cancel latency never
    depend on the author's punctuation habits.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for sentence in split_arabic_sentences(text):
        words = sentence.split()
        if len(words) > CHUNK_TOKENS:
            # Flush the pending chunk first, then window the long sentence.
            if current:
                chunks.append(current)
                current, current_len = [], 0
            for i in range(0, len(words), CHUNK_TOKENS):
                chunks.append([" ".join(words[i : i + CHUNK_TOKENS])])
            continue
        current.append(sentence)
        current_len += len(words)
        if current_len >= CHUNK_TOKENS:
            chunks.append(current)
            current, current_len = [], 0
    if current:
        chunks.append(current)
    # chunks are lists of sentences; the fallback wraps the raw text the
    # same way (split_arabic_sentences returns [] for whitespace-only text).
    return chunks or ([[text]] if text.strip() else [])


def _aggregate(analysis: Any) -> dict[str, Any]:
    """Aggregate one chunk's ArabicAnalysis into frequency tables."""
    pos_counter: Counter[str] = Counter()
    root_counter: Counter[str] = Counter()
    pattern_counter: Counter[str] = Counter()
    lemma_counter: Counter[str] = Counter()
    token_counter: Counter[str] = Counter()
    broken_plurals = 0
    for t in analysis.tokens:
        pos_counter[t.pos] += 1
        token_counter[t.text] += 1
        if t.lemma:
            lemma_counter[t.lemma] += 1
        if t.root:
            root_counter[t.root] += 1
        if t.pattern:
            pattern_counter[t.pattern] += 1
        if t.is_broken_plural:
            broken_plurals += 1
    return {
        "tokens": len(analysis.tokens),
        "broken_plural_count": broken_plurals,
        "pos_distribution": pos_counter,
        "root_counts": root_counter,
        "pattern_counts": pattern_counter,
        "lemma_counts": lemma_counter,
        "token_counts": token_counter,
    }


class _Accumulator:
    """Typed merge accumulator for the per-chunk aggregation."""

    def __init__(self) -> None:
        self.tokens = 0
        self.broken_plural_count = 0
        self.pos_distribution: Counter[str] = Counter()
        self.root_counts: Counter[str] = Counter()
        self.pattern_counts: Counter[str] = Counter()
        self.lemma_counts: Counter[str] = Counter()
        self.token_counts: Counter[str] = Counter()

    def merge(self, chunk_agg: dict[str, Any]) -> None:
        self.tokens += chunk_agg["tokens"]
        self.broken_plural_count += chunk_agg["broken_plural_count"]
        self.pos_distribution.update(chunk_agg["pos_distribution"])
        self.root_counts.update(chunk_agg["root_counts"])
        self.pattern_counts.update(chunk_agg["pattern_counts"])
        self.lemma_counts.update(chunk_agg["lemma_counts"])
        self.token_counts.update(chunk_agg["token_counts"])


class ArabicBulkJob:
    """Single-slot bulk analysis with progress, cancel and a result file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._result_path: Path | None = None
        self._status: dict[str, Any] = {"state": "idle"}

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = dict(self._status)
            s["busy"] = s.get("state") == "running"
            if self._result_path and self._status.get("state") == "done":
                s["result_available"] = self._result_path.is_file()
            return s

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self._status.update(fields)

    def start(self, text: str) -> dict[str, Any]:
        with self._lock:
            if self._status.get("state") == "running" and self._thread and self._thread.is_alive():
                raise BulkBusyError(
                    "A bulk Arabic analysis job is already running. "
                    "Cancel it or wait for it to finish."
                )
            chunks = _chunk_text(text)
            if not chunks:
                raise ValueError("Text is empty.")
            total_tokens = sum(len(" ".join(c).split()) for c in chunks)
            # Drop any stale result file from a previous run only when we
            # actually start new work.
            self._clear_result_file()
            self._cancel.clear()
            self._status = {
                "state": "running",
                "stage": "chunking",
                "chunks_total": len(chunks),
                "chunks_done": 0,
                "tokens_total": total_tokens,
                "tokens_done": 0,
                "elapsed_s": 0,
                "eta_s": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }
            self._thread = threading.Thread(
                target=self._run, args=(chunks,), name="arabic-bulk-analysis", daemon=True
            )
            self._thread.start()
        # status() re-acquires the (non-reentrant) lock: call it OUTSIDE the
        # with-block above or start() deadlocks against itself.
        return self.status()

    def _run(self, chunks: list[list[str]]) -> None:
        try:
            acc = _Accumulator()
            total_tokens = self.status().get("tokens_total", 1) or 1
            started = time.time()
            for i, chunk in enumerate(chunks):
                if self._cancel.is_set():
                    raise _JobCancelledError()
                if time.time() - started > BULK_MAX_S:
                    raise TimeoutError(
                        f"Bulk analysis exceeded its {BULK_MAX_S:g}s ceiling."
                    )
                chunk_text = " ".join(chunk)
                analysis = analyze_arabic(chunk_text, dialect="msa")
                acc.merge(_aggregate(analysis))
                elapsed = time.time() - started
                tokens_done = acc.tokens
                eta = (
                    round(elapsed / tokens_done * (total_tokens - tokens_done), 1)
                    if tokens_done > 0
                    else None
                )
                self._update(
                    stage="analyzing",
                    chunks_done=i + 1,
                    tokens_done=tokens_done,
                    elapsed_s=round(elapsed, 1),
                    eta_s=eta,
                )
            # Build the final aggregate payload (bounded tables)
            result = {
                "kind": "arabic_bulk_analysis",
                "chunks": len(chunks),
                "token_count": acc.tokens,
                "unique_tokens": len(acc.token_counts),
                "broken_plural_count": acc.broken_plural_count,
                "pos_distribution": dict(acc.pos_distribution.most_common()),
                "top_roots": acc.root_counts.most_common(TOP_TABLE_LIMIT),
                "top_patterns": acc.pattern_counts.most_common(TOP_TABLE_LIMIT),
                "top_lemmas": acc.lemma_counts.most_common(TOP_TABLE_LIMIT),
                "top_tokens": acc.token_counts.most_common(TOP_TABLE_LIMIT),
                "generated_at": time.time(),
            }
            out = Path(tempfile.gettempdir()) / f"corpusmind-arabic-bulk-{int(time.time())}.json"
            out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            self._result_path = out
            self._update(
                state="done",
                stage="done",
                finished_at=time.time(),
                result_path=str(out),
                result_bytes=out.stat().st_size,
                unique_tokens=len(acc.token_counts),
            )
            log.info("arabic_bulk_done", tokens=acc.tokens, chunks=len(chunks))
        except _JobCancelledError:
            self._clear_result_file()
            self._update(state="cancelled", stage="idle", finished_at=time.time())
            log.info("arabic_bulk_cancelled")
        except ArabicDataMissingError as e:
            self._update(state="error", stage="idle", finished_at=time.time(), error=str(e))
        except Exception as e:
            self._clear_result_file()
            self._update(
                state="error", stage="idle", finished_at=time.time(),
                error=f"{type(e).__name__}: {e}",
            )
            log.warning("arabic_bulk_failed", error=str(e))

    def _clear_result_file(self) -> None:
        path, self._result_path = self._result_path, None
        if path and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        with self._lock:
            if self._status.get("state") == "running":
                self._status["stage"] = "cancelling"
            s = dict(self._status)
        s["busy"] = s.get("state") == "running"
        return s

    def result_path(self) -> Path | None:
        with self._lock:
            if self._status.get("state") == "done" and self._result_path:
                return self._result_path
            return None


_job: ArabicBulkJob | None = None
_job_lock = threading.Lock()


def get_bulk_job() -> ArabicBulkJob:
    global _job
    with _job_lock:
        if _job is None:
            _job = ArabicBulkJob()
        return _job


def reset_bulk_job_for_tests() -> None:
    global _job
    with _job_lock:
        if _job is not None:
            _job._clear_result_file()
        _job = None

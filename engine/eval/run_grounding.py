"""Run the grounding question bank through the assistant chat endpoint.

Recreates the snapshot corpora exactly like build_gold, then posts every
question to ``POST /api/v1/ai/chat`` with the corpus selected and a context
string that maps symbolic corpus names to their real IDs (so cross-corpus
questions are answerable). The provider is whatever the environment
configures: a local Ollama/LM Studio, the cloud provider, or the repo's
fake provider (scripts/ci_smoke_fake_provider.py) for deterministic smoke
runs. The output is a run JSON consumable by eval/score.py.

Usage (from engine/):
    # real provider (env: CORPUSMIND_CLOUD_* or a running Ollama)
    python -m eval.run_grounding --provider ollama --out runs/run1.json
    # limit / filter
    python -m eval.run_grounding --only G-001 G-007 --provider cloud
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.build_gold import boot_engine
from eval.corpus_snapshot import CORPUS_LAYOUT
from eval.questions import QUESTION_BANK, validate_bank

_RUNS_DIR = Path(__file__).parent / "runs"


def _context_block(corpus_map: dict[str, str]) -> str:
    lines = ["Available corpora for tool calls (name = corpus_id):"]
    for symbol, (name, lang, files) in CORPUS_LAYOUT.items():
        lines.append(f"- {name} ({lang}; {', '.join(files)}) = {corpus_map[symbol]}")
    lines.append(
        "When a tool needs more than one corpus (e.g. keyness), use these IDs "
        "as target/reference arguments exactly as given."
    )
    return "\n".join(lines)


async def run(
    provider: str | None,
    model: str | None,
    only: list[str] | None,
    out: Path | None,
    pause: float = 0.0,
    rate_retries: int = 0,
) -> dict[str, Any]:
    problems = validate_bank()
    if problems:
        raise SystemExit("question bank invalid: " + "; ".join(problems))
    questions = [q for q in QUESTION_BANK if only is None or q["id"] in only]
    results: list[dict[str, Any]] = []
    async with boot_engine() as client:
        from eval.corpus_snapshot import prepare_corpora

        corpus_map = await prepare_corpora(client)
        context = _context_block(corpus_map)
        for i, q in enumerate(questions, 1):
            payload = {
                "message": q["question"],
                "corpus_id": corpus_map[q["corpus"]],
                "context": context,
            }
            if provider:
                payload["provider"] = provider
            if model:
                payload["model"] = model
            if pause > 0:
                await asyncio.sleep(pause)
            t0 = time.monotonic()
            try:
                r = await client.post("/api/v1/ai/chat", json=payload, timeout=300.0)
                # Harness-level rate-limit recovery. The engine's own retry
                # policy (3 attempts, exponential backoff, Retry-After capped
                # at 15 s) is right for an interactive chat turn, but a
                # free-tier cloud quota window (e.g. Gemini ~10 RPM) outlives
                # it: a 429 returned to THIS loop means the engine already
                # exhausted its budget. Re-POSTing the same question after a
                # longer wait is safe (the sweep is read-only), and the wait
                # honours Retry-After when the gateway sends one.
                attempt = 0
                while r.status_code in (429, 503) and attempt < rate_retries:
                    retry_after = 0.0
                    raw = r.headers.get("retry-after", "")
                    try:
                        retry_after = max(0.0, float(raw.strip())) if raw else 0.0
                    except ValueError:
                        retry_after = 0.0
                    wait = min(max(retry_after, 20.0 * (2 ** attempt)), 90.0)
                    attempt += 1
                    print(
                        f"[{i}/{len(questions)}] {q['id']} -> HTTP {r.status_code}; "
                        f"rate-retry {attempt}/{rate_retries} in {wait:.0f}s"
                    )
                    await asyncio.sleep(wait)
                    r = await client.post("/api/v1/ai/chat", json=payload, timeout=300.0)
                if r.status_code >= 400:
                    entry = {"id": q["id"], "answer": "", "http_status": r.status_code,
                             "error": r.text[:300]}
                else:
                    body = r.json()
                    entry = {
                        "id": q["id"],
                        "answer": body.get("content", ""),
                        "grounded": body.get("grounded"),
                        "tool_calls": body.get("tool_calls", []),
                        "evidence": body.get("evidence", []),
                        "elapsed_ms": body.get("elapsed_ms"),
                    }
            except Exception as exc:
                entry = {"id": q["id"], "answer": "", "error": f"{type(exc).__name__}: {exc}"}
            entry["wall_ms"] = int((time.monotonic() - t0) * 1000)
            results.append(entry)
            print(f"[{i}/{len(questions)}] {q['id']} -> {entry.get('error') or 'ok'}")

    run_doc = {
        "meta": {
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "provider": provider,
            "model": model,
            "question_count": len(results),
            "pause_s": pause,
            "rate_retries": rate_retries,
        },
        "results": results,
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(run_doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"run written: {out}")
    return run_doc


def main() -> None:
    ap = argparse.ArgumentParser(description="Run grounding questions via /ai/chat")
    ap.add_argument("--provider", default=None, help="ollama | cloud | lmstudio (default: engine default)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", nargs="*", help="run only these question ids")
    ap.add_argument("--out", default=None, help="output path (default eval/runs/grounding_run_<ts>.json)")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds to sleep BEFORE each question (rate-limit pacing; 7.0 fits free-tier Gemini ~10 RPM)")
    ap.add_argument("--rate-retries", type=int, default=0,
                    help="harness-level re-POSTs on HTTP 429/503 (waits 20/40/80s, Retry-After honoured, 90s cap)")
    args = ap.parse_args()
    out = Path(args.out) if args.out else _RUNS_DIR / (
        "grounding_run_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    asyncio.run(run(args.provider, args.model, args.only, out,
                    pause=args.pause, rate_retries=args.rate_retries))


if __name__ == "__main__":
    main()

"""Student Mode classroom soak test (v1.2.10, checklist item 5b).

Simulates the README §"Practical scale" scenario: a ~100K-token corpus and
20 concurrent students (the MAX_STUDENTS seat cap) hitting the analysis
endpoints the student allowlist exposes. Reports per-endpoint latency
(p50 / p95 / max), success counts, and the engine's RSS before/after.

Also demonstrates the v1.2.10 parse-stream LRU (app/version_cache): the
soak runs TWO identical waves against the discourse lens (the endpoint
backed by _load_parses). Wave 1 pays the SQLite load; wave 2 should be
served warm for all 20 workers.

Usage:  python scripts/soak_student_load.py [--port 8791]
Requires: engine deps installed + the en_core_web_sm spaCy model.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import random
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
STUDENTS = 20
ROUNDS = 2  # requests per endpoint per student per wave (soak budget)

# Small functional vocabulary so queries actually match. Function words and
# a few metadiscourse cues (Hyland lens) appear at realistic rates.
VOCAB = [
    "the", "of", "and", "to", "in", "a", "is", "that", "it", "for", "as",
    "was", "with", "be", "by", "on", "not", "this", "are", "or", "from",
    "we", "I", "you", "they", "he", "she", "our", "their", "one", "all",
    "time", "people", "world", "study", "results", "however", "perhaps",
    "note", "clearly", "important", "according", "data", "analysis",
    "language", "text", "corpus", "method", "theory", "evidence",
]
METADISCOURSE = ["however", "perhaps", "note", "clearly", "important", "we", "I", "our"]


def make_document(rng: random.Random, n_words: int) -> str:
    words = []
    for _ in range(n_words):
        # ~6% metadiscourse cues so the Hyland lens has signal.
        if rng.random() < 0.06:
            words.append(rng.choice(METADISCOURSE))
        else:
            words.append(rng.choice(VOCAB))
    # Sentences of 8-20 words.
    out, i = [], 0
    while i < len(words):
        span = rng.randint(8, 20)
        out.append(" ".join(words[i : i + span]).capitalize() + ".")
        i += span
    return " ".join(out)


def rss_mb(pid: int) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return -1.0


def wait_healthy(timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/api/v1/health", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1.0)
    raise SystemExit("engine did not become healthy")


async def post_json(path: str, payload: dict, token: str | None = None) -> tuple[int, dict | bytes]:
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(f"{BASE}{path}", json=payload, headers=headers)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.content


async def setup_corpus() -> str:
    """Create project + corpus + ~100K tokens across 100 documents."""
    import httpx

    async with httpx.AsyncClient(timeout=600.0) as c:
        r = await c.post(f"{BASE}/api/v1/projects", json={"name": "soak", "language": "en"})
        pid = r.json()["id"]
        r = await c.post(f"{BASE}/api/v1/projects/{pid}/corpora", json={"name": "soak", "language": "en"})
        cid = r.json()["id"]
        rng = random.Random(42)
        files = []
        for i in range(100):  # 100 docs x ~1000 words = ~100K tokens
            text = make_document(rng, 1000)
            files.append(("files", (f"soak_{i:03d}.txt", io.BytesIO(text.encode()), "text/plain")))
        t0 = time.time()
        r = await c.post(f"{BASE}/api/v1/corpora/{cid}/documents", files=files)
        print(f"[soak] upload+annotate 100 docs (~100K tokens): {r.status_code} in {time.time()-t0:.0f}s")
        if r.status_code not in (200, 201):
            print(r.text[:500])
            raise SystemExit(1)
    return cid


async def worker(wid: int, cid: str, endpoints: list[dict], results: list) -> None:
    import httpx

    rng = random.Random(1000 + wid)
    async with httpx.AsyncClient(timeout=180.0) as c:
        for _ in range(ROUNDS):
            for ep in endpoints:
                body = dict(ep["body"])
                if ep["name"] == "concordance":
                    body["query"] = rng.choice(["time", "people", "study", "world"])
                elif ep["name"] == "collocations":
                    body["node"] = rng.choice(["time", "people", "study"])
                t0 = time.perf_counter()
                try:
                    r = await c.post(f"{BASE}{ep['path']}", json=body)
                    ok = r.status_code == 200
                    detail = r.status_code
                except Exception as e:  # noqa: BLE001
                    ok, detail = False, f"{type(e).__name__}: {e}"[:120]
                dt = (time.perf_counter() - t0) * 1000.0
                results.append({"ep": ep["name"], "ok": ok, "ms": dt, "detail": detail})


def summarize(results: list[dict], label: str) -> None:
    print(f"\n[soak] === {label} ===")
    by_ep: dict[str, list[float]] = {}
    fails = 0
    for r in results:
        if r["ok"]:
            by_ep.setdefault(r["ep"], []).append(r["ms"])
        else:
            fails += 1
            if fails <= 3:
                print(f"[soak] FAIL {r['ep']}: {r['detail']}")
    for ep, xs in sorted(by_ep.items()):
        xs.sort()
        p50 = statistics.median(xs)
        p95 = xs[max(0, int(len(xs) * 0.95) - 1)]
        print(f"[soak] {ep:14s} n={len(xs):4d}  p50={p50:8.1f}ms  p95={p95:8.1f}ms  max={xs[-1]:8.1f}ms")
    total = len(results)
    print(f"[soak] requests: {total}, failures: {fails}")


async def main() -> int:
    global PORT, BASE, ROUNDS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    args = ap.parse_args()
    PORT = args.port
    ROUNDS = args.rounds
    BASE = f"http://127.0.0.1:{PORT}"

    os.makedirs("/tmp/cm-soak", exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "CORPUSMIND_DB_URL": "sqlite+aiosqlite:////tmp/cm-soak/soak.db",
            "CORPUSMIND_DATA_DIR": "/tmp/cm-soak/data",
            "CORPUSMIND_LOG_LEVEL": "warning",
        }
    )
    server_log = open("/tmp/cm-soak/server.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=str(REPO / "engine"),
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )
    stop = lambda *_: proc.send_signal(signal.SIGTERM)  # noqa: E731
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    try:
        wait_healthy()
        rss0 = rss_mb(proc.pid)
        print(f"[soak] engine up (pid {proc.pid}), RSS baseline {rss0:.0f} MB")

        cid = await setup_corpus()
        endpoints = [
            {"name": "concordance", "path": f"/api/v1/corpora/{cid}/concordance", "body": {"query": "time", "limit": 200}},
            {"name": "collocations", "path": f"/api/v1/corpora/{cid}/collocations", "body": {"node": "time", "window": 5}},
            {"name": "discourse", "path": f"/api/v1/corpora/{cid}/discourse", "body": {"taxonomy": "hyland2005"}},
        ]

        # Wave 1: 20 students x ROUNDS rounds x 3 endpoints.
        results: list[dict] = []
        t0 = time.time()
        async with asyncio.TaskGroup() as tg:
            for w in range(STUDENTS):
                tg.create_task(worker(w, cid, endpoints, results))
        summarize(results, f"wave 1 (cold cache) — {STUDENTS} students x {ROUNDS} rounds x 3 endpoints, {time.time()-t0:.1f}s wall")
        rss1 = rss_mb(proc.pid)

        # Wave 2: identical — the discourse lens should now be cache-warm.
        results2: list[dict] = []
        t0 = time.time()
        async with asyncio.TaskGroup() as tg:
            for w in range(STUDENTS):
                tg.create_task(worker(w, cid, endpoints, results2))
        summarize(results2, f"wave 2 (warm cache) — identical load, {time.time()-t0:.1f}s wall")
        rss2 = rss_mb(proc.pid)

        print(f"\n[soak] RSS: baseline {rss0:.0f} MB → after wave1 {rss1:.0f} MB → after wave2 {rss2:.0f} MB")
        print("[soak] DONE")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        server_log.close()
        log_text = Path("/tmp/cm-soak/server.log").read_text(errors="replace")
        err_lines = [l for l in log_text.splitlines() if "error" in l.lower() or "Exception" in l]
        if err_lines:
            print(f"[soak] server log error lines ({len(err_lines)}), first 12:")
            for l in err_lines[:12]:
                print("  " + l[:300])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

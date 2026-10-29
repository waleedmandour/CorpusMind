"""Freeze the grounding gold: run every question's tool calls ONCE against
the fixed snapshot corpus and resolve the gold spec into concrete values.

Discipline: this script is the ONLY producer of ``grounding_gold.json``. It
refuses to overwrite an existing gold without ``--force`` (a regeneration is
a reviewable event, not a side effect). Internal-consistency cross-checks
fail the build loudly — a tool output that contradicts another tool output
or an independent recomputation stops the freeze.

Usage (from engine/):
    python -m eval.build_gold             # build gold for all 80 questions
    python -m eval.build_gold --only G-001 G-009
    python -m eval.build_gold --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_GOLD_PATH = Path(__file__).parent / "data" / "gold" / "grounding_gold.json"


@asynccontextmanager
async def boot_engine(db_url: str = "sqlite+aiosqlite:///:memory:") -> AsyncIterator[Any]:
    """Boot the engine app in-process (same pattern as the engine tests)."""
    os.environ["CORPUSMIND_DB_URL"] = db_url
    os.environ.setdefault("CORPUSMIND_DATA_DIR", "/tmp/cm-eval-data")
    os.environ["CORPUSMIND_ARABIC_WARMUP"] = "0"
    from app.settings import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from storage.session import dispose_db

    await dispose_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            yield client
    await dispose_db()


# Per-tool arg-name aliases: question banks use stable short names; the tool
# impls use their own parameter names.
_TOOL_ARG_ALIASES: dict[str, dict[str, str]] = {
    "compute_keyness": {"corpus": "target_corpus_id", "reference": "reference_corpus_id"},
}


def _resolve_args(args: dict[str, Any], corpus_map: dict[str, str], tool: str) -> dict[str, Any]:
    """Symbolic args -> real tool args (corpus symbol -> corpus_id)."""
    aliases = _TOOL_ARG_ALIASES.get(tool, {"corpus": "corpus_id"})
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in aliases:
            out[aliases[k]] = corpus_map[v]
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------- #
# Path resolution
# --------------------------------------------------------------------- #
def _split_path(path: str) -> list[str]:
    """'t0.measures[term=goal].log_ratio' -> ['t0','measures','[term=goal]','log_ratio']
    Literal keys containing dots are written bracketed: 'categories.[interactional.hedges].freq'
    """
    parts: list[str] = []
    for raw in path.split("."):
        while raw:
            if raw.startswith("["):
                close = raw.find("]")
                if close == -1:
                    parts.append(raw)
                    raw = ""
                else:
                    parts.append(raw[: close + 1])
                    raw = raw[close + 1 :]
                continue
            m = re.match(r"^([^\[\]]+)\[(.*?)\](.*)$", raw)
            if m:
                if m.group(1):
                    parts.append(m.group(1))
                parts.append(f"[{m.group(2)}]")
                raw = m.group(3)
            else:
                parts.append(raw)
                raw = ""
    # re-join bracket literals whose content contained dots
    merged: list[str] = []
    for part in parts:
        if merged and merged[-1].startswith("[") and not merged[-1].endswith("]"):
            merged[-1] = merged[-1] + "." + part  # continue an open bracket literal
        else:
            merged.append(part)
    return merged


def _resolve_one(root: Any, path: str) -> tuple[bool, Any]:
    """Resolve 'tN.<path>' against frozen tools. Returns (found, value)."""
    parts = _split_path(path)
    m = re.match(r"^t(\d+)$", parts[0])
    if not m:
        return False, f"bad root '{parts[0]}'"
    tools = root["tools"]
    idx = int(m.group(1))
    if idx >= len(tools):
        return False, f"tool index {idx} out of range"
    cur: Any = tools[idx].get("result")
    indirection: str | None = None
    for part in parts[1:]:
        if part.startswith("[") and part.endswith("]"):
            inner = part[1:-1]
            if inner == "*":
                # wildcard map: resolve the remaining path for every element
                rest = parts[parts.index(part) + 1:]
                if not isinstance(cur, list):
                    return False, "wildcard on non-list"
                values: list[Any] = []
                for el in cur:
                    sub = _resolve_one({"tools": [{"result": el}]}, "t0" + "".join(
                        p if p.startswith("[") else "." + p for p in rest
                    ))
                    if not sub[0]:
                        return False, f"wildcard element failed at {rest}"
                    values.append(sub[1])
                cur = values
                break
            if inner.lstrip("-").isdigit():
                idx = int(inner)
                if not isinstance(cur, list) or idx >= len(cur):
                    return False, f"index {inner} out of range"
                cur = cur[idx]
                continue
            if "=" not in inner:
                if not isinstance(cur, dict) or inner not in cur:
                    return False, f"missing key '{inner}'"
                cur = cur[inner]
                continue
            key, _, val = inner.partition("=")
            if not isinstance(cur, list):
                return False, f"filter on non-list at '{part}'"
            if val.startswith("$"):
                indirection = val[1:]
                val = "__indirect__"
            hit = None
            for item in cur:
                if isinstance(item, dict) and str(item.get(key)) == str(val):
                    hit = item
                    break
            if hit is None:
                return False, f"no row matches '{inner}'"
            cur = hit
        else:
            if not isinstance(cur, dict) or part not in cur:
                return False, f"missing key '{part}'"
            cur = cur[part]
    if indirection is not None:
        # re-resolve the filter value from another path in the same tool set
        found, indirect_val = _resolve_one(root, indirection)
        if not found:
            return False, f"indirection '{indirection}' not resolved"
        # caller matched nothing yet if the filter used the placeholder —
        # redo the whole path with the concrete value.
        concrete = path.replace("$" + indirection, str(indirect_val))
        return _resolve_one(root, concrete)
    return True, cur


def resolve_gold_spec(spec: list[dict[str, Any]], frozen: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Resolve one question's gold spec -> concrete gold block (or error)."""
    numbers: list[dict[str, Any]] = []
    strings: list[dict[str, Any]] = []
    traps: dict[str, Any] = {}
    for g in spec:
        kind = g["kind"]
        if kind == "trap_error":
            traps["error"] = True
            continue
        if kind == "trap_no_tool":
            traps["no_tool"] = True
            continue
        found, value = _resolve_one(frozen, g["path"])
        if kind == "absent":
            if found:
                return None, f"{g['path']}: expected absent but found {value!r}"
            traps.setdefault("absent", []).append(g["label"])
            continue
        if kind == "present":
            if not found:
                return None, f"{g['path']}: expected present but no row matched"
            traps.setdefault("present", []).append(g["label"])
            continue
        if kind == "trap_zero":
            if not found:
                return None, f"{g['path']}: trap_zero path not found"
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value != 0:
                return None, f"{g['path']}: trap_zero expected 0, got {value!r}"
            numbers.append({"label": g["label"], "value": 0, "tol": 0})
            continue
        if not found:
            return None, f"{g['path']}: not found"
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None, f"{g['path']}: expected number, got {type(value).__name__}"
            numbers.append({"label": g["label"], "value": value, "tol": g.get("tol", 1e-6)})
        elif kind == "string":
            strings.append({"label": g["label"], "value": str(value)})
        elif kind == "count":
            if not isinstance(value, list):
                return None, f"{g['path']}: count expects list, got {type(value).__name__}"
            numbers.append({"label": g["label"], "value": len(value), "tol": 0})
        elif kind == "distinct":
            if not isinstance(value, list):
                return None, f"{g['path']}: distinct expects list"
            numbers.append({"label": g["label"], "value": len({json.dumps(v, sort_keys=True) for v in value}), "tol": 0})
        elif kind == "list_each":
            if not isinstance(value, list) or not all(isinstance(v, (int, float)) for v in value):
                return None, f"{g['path']}: list_each expects numeric list, got {value!r}"
            numbers.append({"label": g["label"], "value": [float(v) for v in value], "tol": g.get("tol", 1e-6)})
        elif kind == "argmax":
            if not isinstance(value, dict) or not value:
                return None, f"{g['path']}: argmax expects non-empty dict"
            key = g["argmax"]
            best = max(value.items(), key=lambda kv: kv[1].get(key, 0) if isinstance(kv[1], dict) else kv[1])
            strings.append({"label": g["label"], "value": str(best[0])})
        else:
            return None, f"unknown gold kind '{kind}'"
    return {"numbers": numbers, "strings": strings, "traps": traps}, ""


# --------------------------------------------------------------------- #
# Cross-checks
# --------------------------------------------------------------------- #
def _deep_numbers(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_deep_numbers(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_deep_numbers(v))
    return out


def cross_check(q: dict[str, Any], frozen: dict[str, Any]) -> list[str]:
    """Internal-consistency checks for one question. Returns problems."""
    problems: list[str] = []
    for t in frozen["tools"]:
        result = t.get("result")
        if result is None or not t.get("ok", True):
            continue
        nums = _deep_numbers(result)
        for n in nums:
            if n != n or n in (float("inf"), float("-inf")):
                problems.append(f"{q['id']}: non-finite number in {t['name']} result")
    # overview <-> frequency agreement
    names = [t["name"] for t in frozen["tools"]]
    if "get_corpus_overview" in names and "get_frequency" in names:
        ov = frozen["tools"][names.index("get_corpus_overview")]["result"]
        fr = frozen["tools"][names.index("get_frequency")]["result"]
        if ov["text_side"]["token_count"] != fr["total_tokens"]:
            problems.append(
                f"{q['id']}: overview token_count {ov['text_side']['token_count']} "
                f"!= frequency total_tokens {fr['total_tokens']}"
            )
    # concordance: if total <= limit, every hit must be present
    if "search_concordance" in names:
        r = frozen["tools"][names.index("search_concordance")]["result"]
        if r["total_matches"] <= 10 and len(r["lines"]) != r["total_matches"]:
            problems.append(
                f"{q['id']}: concordance total {r['total_matches']} != {len(r['lines'])} lines"
            )
    # dispersion: per-part frequencies must sum to a positive number
    if "get_dispersion" in names:
        r = frozen["tools"][names.index("get_dispersion")]["result"]
        total = sum(r.get("per_part_freqs", []))
        if total <= 0:
            problems.append(f"{q['id']}: dispersion for {r.get('term')!r} has zero total occurrences")
    return problems


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _spacy_model_info() -> dict[str, str]:
    """Record the annotation model version — part of the gold provenance."""
    try:
        import spacy

        meta = spacy.load("en_core_web_sm").meta
        return {"en_core_web_sm": str(meta.get("version", "unknown"))}
    except Exception as exc:
        return {"en_core_web_sm": f"unavailable: {exc}"}


async def _arabic_ready(client: Any) -> bool:
    """True when Arabic morphology ingest actually works (capability probe,
    independent of the installer's status vocabulary)."""
    r = await client.post("/api/v1/arabic/analyze", json={"text": "كتب الكتاب", "dialect": "msa"})
    return bool(r.status_code == 200)


async def ensure_arabic_pack(client: Any, timeout_s: float = 1500.0) -> dict[str, Any]:
    """Make sure the CAMeL Arabic data pack is usable. Probes the real
    capability first; only starts the pinned installer when analyze fails.
    Returns a small status dict for the gold provenance."""
    import time

    if await _arabic_ready(client):
        return {"status": "ready", "install_started": False}
    r = await client.post("/api/v1/arabic/data/install", json={"force": False})
    started = r.status_code in (200, 201, 202)
    if r.status_code not in (200, 201, 202, 409):
        raise RuntimeError(f"arabic pack install refused: HTTP {r.status_code}: {r.text[:300]}")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        await asyncio.sleep(10)
        if await _arabic_ready(client):
            return {"status": "ready", "install_started": started}
        status = (await client.get("/api/v1/arabic/data/install/status")).json()
        state = status.get("state")
        if state in ("failed", "error", "cancelled"):
            raise RuntimeError(f"arabic pack install failed: {json.dumps(status)[:400]}")
    raise TimeoutError("arabic pack did not become usable in time")


async def build(only: list[str] | None = None) -> dict[str, Any]:
    from ai.tools import execute_tool
    from app import __version__ as engine_version
    from eval.corpus_snapshot import CORPUS_LAYOUT, verify_snapshot
    from eval.questions import QUESTION_BANK, validate_bank

    problems = validate_bank()
    if problems:
        raise SystemExit("question bank invalid: " + "; ".join(problems))
    docs = verify_snapshot()
    questions = [q for q in QUESTION_BANK if only is None or q["id"] in only]

    gold_questions: list[dict[str, Any]] = []
    build_errors: list[str] = []
    async with boot_engine() as client:
        from eval.corpus_snapshot import prepare_corpora

        needs_arabic = any(
            q["corpus"] in ("C4", "C5") or any("arabic" in t["name"] for t in q["tools"])
            for q in questions
        )
        arabic_pack: dict[str, Any] = {"status": "not-needed"}
        if needs_arabic:
            arabic_pack = {"status": "ready", "detail": await ensure_arabic_pack(client)}
        corpus_map = await prepare_corpora(client)
        # independent tokenizer sanity (warn/fail threshold, not gold)
        for symbol, (_name, lang, files) in CORPUS_LAYOUT.items():
            if lang != "en":
                continue
            text = " ".join(d.text for d in docs if d.file in files)
            independent = len(re.findall(r"[A-Za-z][A-Za-z'’-]*", text))
            r = await client.post(
                f"/api/v1/corpora/{corpus_map[symbol]}/frequency", json={"unit": "word", "limit": 1}
            )
            engine_total = r.json()["total_tokens"]
            drift = abs(independent - engine_total) / max(1, independent)
            if drift > 0.20:
                build_errors.append(
                    f"independent tokenizer vs engine drift {drift:.0%} for {symbol} "
                    f"({independent} vs {engine_total})"
                )
        for q in questions:
            frozen_tools: list[dict[str, Any]] = []
            tool_failed_unexpectedly = False
            for t in q["tools"]:
                args = _resolve_args(t["args"], corpus_map, t["name"])
                try:
                    result = await execute_tool(t["name"], args)
                    frozen_tools.append({"name": t["name"], "args": t["args"], "ok": True, "result": result})
                except Exception as exc:
                    frozen_tools.append({
                        "name": t["name"], "args": t["args"], "ok": False, "error": str(exc)[:300],
                    })
                    tool_failed_unexpectedly = True
            entry: dict[str, Any] = {
                "id": q["id"],
                "category": q["category"],
                "language": q["language"],
                "corpus": q["corpus"],
                "question": q["question"],
                "trap": q.get("trap", False),
                "tools": frozen_tools,
            }
            wants_error = any(g["kind"] == "trap_error" for g in q["gold_spec"])
            if wants_error and not tool_failed_unexpectedly:
                build_errors.append(f"{q['id']}: expected the tool call to fail (trap_error) but it succeeded")
                continue
            if tool_failed_unexpectedly and not wants_error:
                err = frozen_tools[0].get("error", "unknown")
                build_errors.append(f"{q['id']}: tool call failed unexpectedly: {err}")
                continue
            gold, err = resolve_gold_spec(q["gold_spec"], {"tools": frozen_tools})
            if gold is None:
                build_errors.append(f"{q['id']}: {err}")
                continue
            if q.get("trap"):
                nonzero = [
                    n for n in gold["numbers"]
                    if isinstance(n["value"], (int, float)) and not isinstance(n["value"], list) and n["value"] != 0
                ]
                if nonzero:
                    build_errors.append(
                        f"{q['id']}: trap question resolved to non-zero gold {nonzero} — rewrite the question"
                    )
                    continue
            entry["gold"] = gold
            problems = cross_check(entry, {"tools": frozen_tools})
            if problems:
                build_errors.extend(problems)
                continue
            gold_questions.append(entry)

    if build_errors:
        print("GOLD BUILD FAILED — nothing written.", file=sys.stderr)
        for e in build_errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(1)

    gold_doc = {
        "_meta": {
            "description": (
                "Frozen grounding gold for the fixed snapshot corpus. Produced ONCE by "
                "eval/build_gold.py from the engine's own tool registry; every numeric answer "
                "the assistant gives is scored against these values. Do not regenerate silently: "
                "a rebuild must be reviewed like any golden-file change (see measures_v2.json "
                "discipline). Tool outputs are frozen verbatim as provenance."
            ),
            "engine_version": engine_version,
            "git_commit": _git_commit(),
            "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "spacy_model": _spacy_model_info(),
            "arabic_pack": {k: v for k, v in arabic_pack.items() if k != "detail"} if "detail" in arabic_pack else arabic_pack,
            "snapshot": {d.file: d.sha256 for d in docs},
            "corpus_layout": {k: {"name": v[0], "language": v[1], "files": v[2]} for k, v in CORPUS_LAYOUT.items()},
            "question_count": len(gold_questions),
        },
        "corpus_map": corpus_map,
        "questions": gold_questions,
    }
    return gold_doc


def main() -> None:
    ap = argparse.ArgumentParser(description="Freeze grounding gold")
    ap.add_argument("--only", nargs="*", help="build only these question ids")
    ap.add_argument("--force", action="store_true", help="overwrite an existing gold file")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap.parse_args()
    if _GOLD_PATH.exists() and not args.force and not args.only:
        raise SystemExit(
            f"{_GOLD_PATH} already exists. Regeneration is a reviewable event: "
            "re-run with --force after diffing the existing gold."
        )
    doc = asyncio.run(build(args.only))
    if args.stdout or args.only:
        print(json.dumps(doc, ensure_ascii=False, indent=1)[:4000])
    if not args.only:
        if _GOLD_PATH.exists() and not args.force:
            raise SystemExit("refusing to overwrite (use --force)")
        _GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
        _GOLD_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"gold written: {_GOLD_PATH} ({doc['_meta']['question_count']} questions)")


if __name__ == "__main__":
    main()

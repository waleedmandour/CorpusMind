#!/usr/bin/env python3
"""Record Ollama provenance for a local grounding run (ollama_env.json).

Mirrors the "Record Ollama provenance" step of .github/workflows/benchmarks.yml
so a local CPU run produces the same provenance artifact that CI attaches to
every committed grounding result (repo convention since #72/#78: every
paper_run.json / paper_report.json pair ships with an ollama_env.json).

Usage (repo root, after `ollama serve` is up and the model is pulled):

    python scripts/record_ollama_env.py --model qwen2.5:3b
    OLLAMA_CONTEXT_LENGTH=16384 python scripts/record_ollama_env.py \
        --model qwen2.5:3b --out engine/eval/runs/ollama_env.json

Stdlib only; requires `ollama` on PATH and the local server reachable.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = "http://127.0.0.1:11434"
DEFAULT_PIN = "0.40.13"
CONTEXT_NOTE = (
    "v2.0.2 engine does not expose num_ctx; the server-side default governs "
    "truncation (OLLAMA_CONTEXT_LENGTH here, else the Ollama build default)"
)


def ollama_version(server: str) -> str:
    try:
        out = subprocess.run(
            ["ollama", "--version"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        # Fall back to the server's version route.
        try:
            with urllib.request.urlopen(f"{server}/api/version", timeout=5) as r:
                return "ollama version is " + json.load(r).get("version", "unknown")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError):
            return "unknown"


def config_digest(server: str, model: str) -> tuple[str, str]:
    """Resolve the model config digest via the OCI manifest path, falling
    back to `ollama ls` (same two-step as the CI step)."""
    base, _, tag = model.partition(":")
    if not tag:
        tag = "latest"
    if "/" not in base:
        base = f"library/{base}"
    url = f"{server}/v2/{base}/manifests/{tag}"
    accept = (
        "application/vnd.oci.image.manifest.v1+json,"
        "application/vnd.docker.distribution.manifest.v2+json"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": accept})
        with urllib.request.urlopen(req, timeout=10) as r:
            digest = json.load(r).get("config", {}).get("digest", "")
        if digest:
            return digest, "registry manifest (v2 API)"
    except (OSError, urllib.error.URLError, json.JSONDecodeError, AttributeError):
        print(f"[record_ollama_env] OCI manifest lookup failed for {url}; "
              "falling back to `ollama ls`", file=sys.stderr)
    try:
        out = subprocess.run(["ollama", "ls"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(
            f"could not resolve model digest for {model}: OCI manifest lookup "
            f"failed and `ollama ls` is unavailable ({e}); is the server up "
            "and the model pulled?"
        ) from e
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == model:
            return parts[1], "ollama ls (short id)"
    raise SystemExit(f"could not resolve model digest for {model}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, help="e.g. qwen2.5:3b")
    ap.add_argument("--pin", default=DEFAULT_PIN, help="installed Ollama release pin")
    ap.add_argument(
        "--server", default=DEFAULT_SERVER, help="Ollama server base URL"
    )
    ap.add_argument(
        "--out",
        default="engine/eval/runs/ollama_env.json",
        help="output path (default: engine/eval/runs/ollama_env.json)",
    )
    args = ap.parse_args()

    digest, digest_src = config_digest(args.server, args.model)
    ctx = os.environ.get("OLLAMA_CONTEXT_LENGTH")
    doc = {
        "utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "ollama_version": ollama_version(args.server),
        "install_pin": args.pin,
        "model": args.model,
        "config_digest": digest,
        "config_digest_source": digest_src,
        "context": {
            "OLLAMA_CONTEXT_LENGTH_env": int(ctx) if ctx else None,
            "note": CONTEXT_NOTE,
        },
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(out.read_text(), end="")
    sys.exit(0)


if __name__ == "__main__":
    main()

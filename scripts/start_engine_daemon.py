#!/usr/bin/env python3
"""Start corpusmind-engine as a fully detached daemon.

Usage: python scripts/start_engine_daemon.py
"""
import os
import sys
import subprocess
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
VENV_PYTHON = ENGINE_DIR / ".venv" / "bin" / "python"
LOG_FILE = "/tmp/cm-engine.log"
DB_FILE = "/tmp/cm-test.db"
DATA_DIR = "/tmp/cm-data"

env = os.environ.copy()
env["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{DB_FILE}"
env["CORPUSMIND_DATA_DIR"] = DATA_DIR
env["CORPUSMIND_HOST"] = "127.0.0.1"
env["CORPUSMIND_PORT"] = "8765"
env["CORPUSMIND_LOG_LEVEL"] = "info"

# Clean previous DB to start fresh
try:
    os.unlink(DB_FILE)
except FileNotFoundError:
    pass

# Detach completely: new session, no shared stdin/stdout/stderr
with open(LOG_FILE, "w") as logf:
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8765", "--log-level", "info"],
        cwd=str(ENGINE_DIR),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detach from our process group
    )

print(f"Started engine daemon PID={proc.pid}")
print(f"Log: {LOG_FILE}")

# Wait for it to be healthy
import urllib.request
for _ in range(30):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/v1/health", timeout=1) as r:
            if r.status == 200:
                print(f"Engine healthy: {r.read().decode()}")
                sys.exit(0)
    except Exception:
        time.sleep(0.5)

print("Engine did not become healthy in 15s — check log:")
print(open(LOG_FILE).read()[-2000:])
sys.exit(1)

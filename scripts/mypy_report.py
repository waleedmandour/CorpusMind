"""mypy strict regression report (v1.2.10) — count, don't chase zero.

The engine is NOT mypy-clean under the project's ``strict = true`` config
(1,700+ errors incl. tests at v1.2.10). Chasing zero is not planned; what
matters is that the count never QUIETLY GROWS. This script:

  1. runs mypy once over the engine (project config applies),
  2. attributes every error to its top-level package (api, app, ai, ..., tests),
  3. compares per-package counts against ``engine/mypy-baseline.json``,
  4. exits 1 if ANY package exceeds its baseline (regression),
     exits 0 on equal-or-fewer (fixes are welcomed; the baseline is not
     auto-lowered — rerun with ``--update`` to lock in improvements).

On CI this runs as a non-blocking job (``continue-on-error``), so the
report is visible without gating merges; the regression gate still makes
a red report meaningful.

Usage:
  python scripts/mypy_report.py            # compare against baseline
  python scripts/mypy_report.py --update   # rewrite baseline from this run
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
BASELINE = Path(__file__).resolve().parent.parent / "engine" / "mypy-baseline.json"

# mypy output line: "path/to/file.py:12: error: ... [code]"
_LINE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+): error: ")


def run_mypy() -> Counter[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "."],
        cwd=ENGINE_DIR,
        capture_output=True,
        text=True,
        timeout=900,
    )
    counts: Counter[str] = Counter()
    for raw in proc.stdout.splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        top = Path(m.group("path")).parts[0] if Path(m.group("path")).parts else "?"
        counts[top] += 1
    # mypy sometimes fails wholesale (config error, crash) — surface that.
    tail = (proc.stdout or "") + (proc.stderr or "")
    if "Found" in tail and "error" in tail:
        pass
    elif proc.returncode not in (0, 1):
        print(f"[mypy-report] mypy exited {proc.returncode}; last output:")
        print(tail[-2000:])
        raise SystemExit(2)
    return counts


def main() -> int:
    update = "--update" in sys.argv
    counts = run_mypy()

    if update or not BASELINE.exists():
        BASELINE.write_text(json.dumps(dict(sorted(counts.items())), indent=2) + "\n")
        total = sum(counts.values())
        print(f"[mypy-report] baseline written: {BASELINE} ({total} errors, {len(counts)} groups)")
        for pkg, n in sorted(counts.items()):
            print(f"  {pkg:20s} {n}")
        return 0

    baseline = json.loads(BASELINE.read_text())
    regressions: list[str] = []
    print(f"{'package':20s} {'baseline':>9s} {'now':>7s} {'delta':>7s}")
    for pkg in sorted(set(baseline) | set(counts)):
        b, n = baseline.get(pkg, 0), counts.get(pkg, 0)
        mark = ""
        if n > b:
            mark = "  REGRESSION"
            regressions.append(f"{pkg}: {b} -> {n}")
        print(f"{pkg:20s} {b:>9d} {n:>7d} {n - b:>+7d}{mark}")
    total_b, total_n = sum(baseline.values()), sum(counts.values())
    print(f"{'TOTAL':20s} {total_b:>9d} {total_n:>7d} {total_n - total_b:>+7d}")

    if regressions:
        print("[mypy-report] FAIL: mypy strict error count regressed:")
        for r in regressions:
            print(f"  - {r}")
        return 1
    print("[mypy-report] PASS: no regression from baseline (lower is fine; run with --update to lock it in)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

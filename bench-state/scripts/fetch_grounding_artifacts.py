#!/usr/bin/env python3
"""Fetch grounding artifacts for given Benchmarks run ids and derive clean answers.

Clean answer = non-empty 'answer' AND no 'error' key (run_grounding.py convention).
Raw artifacts kept under /home/z/my-project/bench_artifacts/run-<id>/.
"""
import io
import json
import os
import sys
import urllib.request
import zipfile

REPO = "waleedmandour/CorpusMind"
TOKEN = os.environ["GH_TOKEN"]
OUT = "/home/z/my-project/bench_artifacts"
RUNS = sys.argv[1:] or [
    "41120607735", "41125306050", "41127495897", "41129889514", "41134947351",
]


def api(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url):
    # First hop: authenticated against api.github.com. GitHub replies 302 to a
    # signed blob URL; the auth header must NOT be sent there.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with opener.open(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307):
            raise
        loc = e.headers["Location"]
        bare = urllib.request.Request(loc, headers={"Accept": "application/zip"})
        with urllib.request.urlopen(bare, timeout=300) as r2:
            return r2.read()


def clean_table(path):
    d = json.load(open(path))
    meta = d.get("meta", {})
    rows = []
    for item in d.get("results", []):
        ans = item.get("answer") or ""
        err = item.get("error")
        rows.append((item["id"], "CLEAN" if (ans.strip() and not err) else "DIRTY",
                     (err or "")[:60]))
    return meta, rows


def main():
    os.makedirs(OUT, exist_ok=True)
    for run in RUNS:
        dest = os.path.join(OUT, f"run-{run}")
        if not os.path.exists(dest):
            os.makedirs(dest)
            arts = api(f"https://api.github.com/repos/{REPO}/actions/runs/{run}/artifacts")
            names = [a["name"] for a in arts.get("artifacts", [])]
            print(f"[run {run}] artifacts: {names}")
            for a in arts.get("artifacts", []):
                blob = download(a["archive_download_url"])
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    z.extractall(dest)
                print(f"  artifact {a['name']} ({a['size_in_bytes']}B) extracted")
        else:
            print(f"[run {run}] already on disk")
        found = False
        for root, _dirs, files in os.walk(dest):
            for f in sorted(files):
                if f.endswith(".json"):
                    p = os.path.join(root, f)
                    try:
                        meta, rows = clean_table(p)
                    except Exception:
                        continue
                    found = True
                    clean = [r[0] for r in rows if r[1] == "CLEAN"]
                    dirty = [r for r in rows if r[1] == "DIRTY"]
                    print(f"  {os.path.relpath(p, dest)}: model={meta.get('model')} "
                          f"clean={len(clean)}/{len(rows)}")
                    for r in dirty:
                        print(f"    DIRTY {r[0]}: {r[2]}")
                    if clean:
                        print(f"    CLEAN ids: {','.join(clean)}")
        if not found:
            print(f"  [run {run}] no grounding JSON artifact found")


if __name__ == "__main__":
    main()

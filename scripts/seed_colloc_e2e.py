#!/usr/bin/env python3
"""Seed a small corpus with strong collocations for the network E2E test."""
import io
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765/api/v1"


def post(path: str, data: bytes, content_type: str) -> dict:
    req = urllib.request.Request(
        BASE + path, data=data, method="POST", headers={"Content-Type": content_type}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main() -> int:
    patterns = [
        "Climate change affects coastal cities in every region of the world today.",
        "Governments must reduce carbon emissions before global warming becomes irreversible.",
        "Renewable energy from solar panels and wind turbines replaces fossil fuels.",
        "Greenhouse gas concentrations reached a record level according to climate scientists.",
        "The paris agreement encourages nations to cut greenhouse gas emissions together.",
        "Rising sea levels threaten low lying islands as ocean temperatures continue to rise.",
        "Clean energy investment creates jobs while reducing air pollution in urban areas.",
        "Scientists warn that extreme weather events will intensify as the planet warms further.",
    ]
    paragraphs = []
    for i in range(240):
        paragraphs.append(" ".join(patterns[(i * 3 + k) % len(patterns)] for k in range(3)))

    project = post("/projects", json.dumps({"name": "E2E Network"}).encode(), "application/json")
    pid = project["id"]
    corpus = post(
        f"/projects/{pid}/corpora",
        json.dumps({"name": "Collocation Demo"}).encode(),
        "application/json",
    )
    cid = corpus["id"]

    boundary = "----cmseed1234"
    parts = []
    for d in range(6):
        text = ("\n\n".join(paragraphs[d * 40 : (d + 1) * 40])).encode()
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
            f"filename=\"climate_report_{d}.txt\"\r\nContent-Type: text/plain\r\n\r\n"
        )
        parts.append(text)
        parts.append(b"\r\n")
    body = b"".join(p if isinstance(p, bytes) else p.encode() for p in parts) + f"--{boundary}--\r\n".encode()

    docs = post(f"/corpora/{cid}/documents", body, f"multipart/form-data; boundary={boundary}")
    print(f"uploaded {len(docs)} documents", file=sys.stderr)

    rec = post(f"/corpora/{cid}/recompile", b"", "application/json")
    print(json.dumps({"project_id": pid, "corpus_id": cid, "recompile": rec}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

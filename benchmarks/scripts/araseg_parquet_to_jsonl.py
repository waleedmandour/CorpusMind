"""Convert an AraSEG shared-task parquet split into the JSONL the eval modules read.

The AraSEG datasets are published on Hugging Face as parquet
(`data/dev-00000-of-00001.parquet`), while `eval.segmentation_araseg` and
`eval.segmentation_downstream` ingest JSON Lines with `doc_id` / `tokens` /
`labels`. This converter is the single parquet-to-JSONL hop; it validates rows
exactly as strictly as `load_documents()` and records provenance (source URL,
parquet sha256, row counts) in a side-car `<out>.meta.json` so a results
snapshot can always be traced back to the exact data snapshot.

Field mapping mirrors `load_documents()`: doc_id falls back to
`document_id`/`id`; labels fall back to `sentence_boundaries`. Rows that
`load_documents()` would silently skip are counted and reported (skipped).

Usage:
    python benchmarks/scripts/araseg_parquet_to_jsonl.py \
        --parquet /tmp/araseg/PA_dev.parquet --out /tmp/araseg/PA/dev.jsonl \
        --source https://huggingface.co/datasets/MBZUAI/AraSeg-2026-Shared-Task-PA
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    import pyarrow.parquet as pq  # deferred: only this tool needs pyarrow

    ap = argparse.ArgumentParser(description="AraSEG parquet -> eval JSONL")
    ap.add_argument("--parquet", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help="output JSONL path")
    ap.add_argument("--source", default=None, help="dataset URL recorded in the meta side-car")
    args = ap.parse_args()

    table = pq.read_table(args.parquet)
    cols = list(table.column_names)

    id_col = next((c for c in ("doc_id", "document_id", "id") if c in cols), None)
    labels_col = next((c for c in ("labels", "sentence_boundaries") if c in cols), None)
    if id_col is None or "tokens" not in cols or labels_col is None:
        raise SystemExit(
            f"unexpected parquet schema {cols}: need doc_id|document_id|id, tokens, "
            "labels|sentence_boundaries — adapt load_documents() contract first"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    kept = skipped = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for row in table.to_pylist():
            doc_id = str(row.get(id_col) or "")
            tokens = [str(t) for t in (row.get("tokens") or [])]
            labels = [int(b) for b in (row.get(labels_col) or [])]
            if not doc_id or not tokens or len(labels) != len(tokens):
                skipped += 1
                continue
            fh.write(json.dumps({"doc_id": doc_id, "tokens": tokens, "labels": labels},
                                ensure_ascii=False, separators=(",", ":")) + "\n")
            kept += 1

    meta = {
        "source": args.source,
        "parquet": args.parquet.name,
        "parquet_sha256": _sha256(args.parquet),
        "parquet_bytes": args.parquet.stat().st_size,
        "columns": cols,
        "rows_kept": kept,
        "rows_skipped": skipped,
        "out_sha256": _sha256(args.out),
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    meta_path = args.out.with_suffix(args.out.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"[convert] {kept} documents kept, {skipped} skipped -> {args.out}")
    print(f"[convert] meta: {meta_path}")


if __name__ == "__main__":
    main()

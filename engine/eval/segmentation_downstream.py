"""Downstream (extrinsic) impact of Arabic segmentation quality.

The AraSEG paper demonstrates extrinsic impact for dependency parsing only.
This module measures it for the corpus-linguistics consumers of sentence
boundaries in THIS engine — the tasks a linguist actually runs:

    KWIC sentence context, same-sentence collocations, n-gram extraction,
    CQL ``within sentence`` scope, per-sentence sentiment, learner CAF
    sentence statistics, and Gale-Church sentence alignment (optional EN side).

Design: for one AraSEG document (tokens + gold boundary labels) build TWO
single-document Arabic corpora in a scratch engine:
  - ENGINE segmentation: the detokenized text, segmented by the engine itself;
  - GOLD segmentation: the same text with newlines inserted at the gold
    boundaries (the engine's splitter always breaks on newlines, so the
    ingest segmentation equals the gold segmentation).
Both are ingested through the real pipeline; every consumer endpoint then
runs on both corpora and the report contains the paired deltas. A large
delta on a consumer is direct evidence that segmentation errors propagate
into that analysis.

Usage (from engine/):
    python -m eval.segmentation_downstream --data /path/araseg/dev.jsonl \
        [--limit 5] [--en-text file.txt] [--out report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from eval.build_gold import boot_engine
from eval.segmentation_araseg import load_documents, predict_boundaries


def gold_text(tokens: list[str], labels: list[int]) -> str:
    """Detokenized text with newlines at gold sentence boundaries."""
    out: list[str] = []
    buf: list[str] = []
    for tok, lab in zip(tokens, labels, strict=False):
        buf.append(tok)
        if lab == 1:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return "\n\n".join(out)


def engine_text(tokens: list[str]) -> str:
    return " ".join(tokens)


async def _ingest(client: Any, text: str) -> str:
    r = await client.post("/api/v1/projects", json={"name": "seg-delta", "language": "ar"})
    r.raise_for_status()
    pid = r.json()["id"]
    r = await client.post(
        f"/api/v1/projects/{pid}/corpora", json={"name": "seg-delta", "language": "ar"}
    )
    r.raise_for_status()
    cid: str = str(r.json()["id"])
    r = await client.post(
        f"/api/v1/corpora/{cid}/documents",
        files={"files": ("doc.txt", text.encode("utf-8"), "text/plain")},
    )
    r.raise_for_status()
    return cid


async def _post(client: Any, url: str, payload: dict[str, Any] | None = None) -> Any:
    r = await client.post(url, json=payload or {})
    if r.status_code >= 400:
        return {"_http_error": r.status_code, "detail": r.text[:200]}
    return r.json()


async def measure_pair(client: Any, engine_cid: str, gold_cid: str, en_cid: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # sentence structure
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await _post(client, f"/api/v1/corpora/{cid}/frequency", {"unit": "word", "limit": 1})
        out.setdefault("tokens", {})[label] = r.get("total_tokens")
    sents = {}
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await client.get(f"/api/v1/corpora/{cid}/documents/stats")
        items = r.json().get("items", []) if r.status_code < 400 else []
        sents[label] = sum(int(i.get("sentences", 0)) for i in items)
    out["sentences"] = sents
    out["delta_sentences"] = sents["gold"] - sents["engine"]

    # same-sentence collocations (window sweep never crosses engine sentences)
    colloc = {}
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await _post(
            client, f"/api/v1/corpora/{cid}/collocations",
            {"node": "في", "window": 5, "min_freq": 1, "level": "word"},
        )
        rows = r.get("top_collocates", []) if isinstance(r, dict) else []
        colloc[label] = {"rows": len(rows), "sum_O": sum(int(x.get("O", 0)) for x in rows)}
    out["collocations"] = {
        "rows_delta": colloc["gold"]["rows"] - colloc["engine"]["rows"],
        "sum_O_delta": colloc["gold"]["sum_O"] - colloc["engine"]["sum_O"],
        **{f"{k}_{l}": v for l, d in colloc.items() for k, v in d.items()},
    }

    # n-grams: sentence-bounded bundles shift with segmentation
    ngrams = {}
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await _post(
            client, f"/api/v1/corpora/{cid}/ngrams",
            {"n": 3, "min_freq": 2, "min_range": 1, "limit": 50},
        )
        rows = r.get("top_ngrams", []) if isinstance(r, dict) else []
        ngrams[label] = {"rows": len(rows), "sum_freq": sum(int(x.get("freq", 0)) for x in rows)}
    out["ngrams"] = {
        "rows_delta": ngrams["gold"]["rows"] - ngrams["engine"]["rows"],
        "sum_freq_delta": ngrams["gold"]["sum_freq"] - ngrams["engine"]["sum_freq"],
    }

    # CQL within sentence scope
    cql = {}
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await _post(
            client, f"/api/v1/corpora/{cid}/concordance/cql",
            {"query": '"في" within sentence', "window": 2},
        )
        cql[label] = r.get("total") if isinstance(r, dict) else None
    out["cql_within_sentence"] = {
        "engine": cql["engine"], "gold": cql["gold"],
        "delta": (cql["gold"] or 0) - (cql["engine"] or 0),
    }

    # per-sentence sentiment
    sent: dict[str, dict[str, Any] | None] = {}
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await _post(client, f"/api/v1/corpora/{cid}/sentiment")
        if isinstance(r, dict) and "_http_error" not in r:
            sent[label] = {
                "total": r.get("total_sentences"),
                "positive": r.get("positive"),
                "negative": r.get("negative"),
                "avg": r.get("avg_score"),
            }
        else:
            sent[label] = None
    se, sg = sent["engine"], sent["gold"]
    if se is not None and sg is not None:
        out["sentiment"] = {
            "delta_total": (sg["total"] or 0) - (se["total"] or 0),
            "delta_positive": (sg["positive"] or 0) - (se["positive"] or 0),
            "delta_negative": (sg["negative"] or 0) - (se["negative"] or 0),
            "delta_avg": (sg["avg"] or 0) - (se["avg"] or 0),
        }

    # learner CAF sentence statistics
    caf: dict[str, dict[str, Any] | None] = {}
    for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
        r = await _post(client, f"/api/v1/corpora/{cid}/learner/caf", {})
        if isinstance(r, dict) and "_http_error" not in r and r.get("overall"):
            o = r["overall"]
            caf[label] = {
                "sentences": o.get("sentences") or (o.get("caf") or {}).get("sentences"),
                "mean_sentence_length": (o.get("caf") or {}).get("mean_sentence_length"),
            }
        else:
            caf[label] = None
    ce, cg = caf["engine"], caf["gold"]
    if ce is not None and cg is not None:
        out["caf"] = {
            "delta_mean_sentence_length": (cg["mean_sentence_length"] or 0)
            - (ce["mean_sentence_length"] or 0),
        }

    # Gale-Church alignment (optional EN parallel side)
    if en_cid is not None:
        align = {}
        for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
            r = await _post(
                client, "/api/v1/bilingual/align",
                {"ar_corpus_id": cid, "en_corpus_id": en_cid},
            )
            align[label] = r.get("pair_count") if isinstance(r, dict) else None
        if align["engine"] is not None and align["gold"] is not None:
            out["alignment_pair_count"] = {"engine": align["engine"], "gold": align["gold"]}
    return out


async def run(data: Path, limit: int | None, en_text: Path | None, out: Path | None) -> dict[str, Any]:
    docs = load_documents(data, limit)
    if not docs:
        raise SystemExit("no usable documents — check eval/data/araseg/README.md")
    en_cid: str | None = None
    async with boot_engine() as client:
        if en_text is not None:
            en_cid = await _ingest(client, en_text.read_text(encoding="utf-8"))
        reports = []
        for doc in docs:
            pred_bits = predict_boundaries(doc["tokens"])
            seg_errors = sum(1 for p, g in zip(pred_bits, doc["labels"], strict=False) if p != g)
            engine_cid = await _ingest(client, engine_text(doc["tokens"]))
            gold_cid = await _ingest(client, gold_text(doc["tokens"], doc["labels"]))
            pair = await measure_pair(client, engine_cid, gold_cid, en_cid)
            reports.append({"doc_id": doc["doc_id"], "boundary_errors": seg_errors,
                            "tokens": len(doc["tokens"]), **pair})
            print(f"{doc['doc_id']}: boundary_errors={seg_errors}, "
                  f"delta_sentences={pair.get('delta_sentences')}")
    report = {"documents": len(reports), "pairs": reports}
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report written: {out}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Segmentation downstream-delta eval")
    ap.add_argument("--data", required=True, help="AraSEG JSONL (doc_id/tokens/labels)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--en-text", type=Path, default=None,
                    help="optional English parallel text for the alignment delta")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    asyncio.run(run(args.data, args.limit, args.en_text, args.out))


if __name__ == "__main__":
    main()

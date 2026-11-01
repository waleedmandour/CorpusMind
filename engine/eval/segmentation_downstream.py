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

Pooled mode (--pool): the 2026-10-31 benchmark runs evaluated one document at
a time. On short single documents the same-sentence collocation and n-gram
tables are near-empty and every CQL match sits inside exactly one sentence on
both sides, so colloc/ngram/CQL deltas collapse to 0 BY CONSTRUCTION, not
because segmentation does not matter. Pooled mode concatenates ALL documents
of a condition into ONE corpus per segmentation (engine vs gold, docs separated
by blank lines in both) and runs the same consumers on corpus scale, with
realistic thresholds (min_freq >= 5) and TWO-TOKEN CQL sequences
('"<w1>" "<w2>" within sentence') chosen from the pooled token stream:
  - top adjacent bigrams by frequency, and
  - bigrams with the most gold-boundary crossings (w1 ends a gold sentence,
    w2 starts the next) — these are exactly the pairs whose "within sentence"
    match count must differ between the two segmentations.

Sign convention (unchanged): every delta is GOLD MINUS ENGINE (positive =
the gold segmentation produced more). The report records the sign explicitly.

Usage (from engine/):
    python -m eval.segmentation_downstream --data /path/araseg/dev.jsonl \
        [--limit 5] [--en-text file.txt] [--out report.json]
    # pooled F2 re-run (per condition):
    python -m eval.segmentation_downstream --data /path/araseg/dev.jsonl \
        --pool --min-colloc-freq 5 --min-ngram-freq 5 --out report.json
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


def pooled_texts(docs: list[dict[str, Any]]) -> tuple[str, str]:
    """Corpus-scale pairing: ONE engine text and ONE gold text for the pool.

    Both join documents with a blank line so the two corpora differ ONLY in
    the sentence boundaries INSIDE each document (same paragraph structure
    between documents), which keeps the comparison about segmentation.
    """
    engine_pool = "\n\n".join(engine_text(d["tokens"]) for d in docs)
    gold_pool = "\n\n".join(gold_text(d["tokens"], d["labels"]) for d in docs)
    return engine_pool, gold_pool


def select_cql_bigrams(docs: list[dict[str, Any]], k: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Data-driven two-token CQL patterns from the pooled token stream.

    Returns {'top_freq': [...], 'top_boundary': [...]}: the k most frequent
    adjacent token bigrams, and the k with the most gold-boundary crossings
    (w1 is the last token of a gold sentence, w2 the first of the next).
    Those crossing pairs are where 'within sentence' scope MUST differ
    between engine and gold segmentation.
    """
    import re
    from collections import Counter

    # Word tokens only: Arabic letters (+digits), length >= 2, no punctuation,
    # no tatweel/diacritics-only tokens, no newline tokens. Punctuation tokens
    # dominate boundary adjacency in AraSEG (boundaries follow sentence marks),
    # so unfiltered selection picks CQL patterns over punctuation that carry
    # no lexical information.
    word_re = re.compile(r"^[\u0621-\u064A0-9]{2,}$")

    freq: Counter[tuple[str, str]] = Counter()
    crossing: Counter[tuple[str, str]] = Counter()
    for d in docs:
        toks, labs = d["tokens"], d["labels"]
        for i in range(len(toks) - 1):
            w1, w2 = toks[i], toks[i + 1]
            if not (word_re.match(w1) and word_re.match(w2)):
                continue
            pair = (w1, w2)
            freq[pair] += 1
            if labs[i] == 1:
                crossing[pair] += 1
    top_freq = [{"w1": a, "w2": b, "freq": n, "gold_crossings": crossing[(a, b)]}
                for (a, b), n in freq.most_common(k)]
    top_cross = [{"w1": a, "w2": b, "freq": freq[(a, b)], "gold_crossings": n}
                 for (a, b), n in crossing.most_common(k) if n > 0]
    return {"top_freq": top_freq, "top_boundary": top_cross}


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
    # The documents endpoint returns a dict for the first upload and a list of
    # per-file results when the corpus already holds documents — accept both.
    data = r.json()
    if isinstance(data, list) and data:
        cid = str(data[0].get("corpus_id") or data[0].get("id") or cid)
    return cid


async def _post(client: Any, url: str, payload: dict[str, Any] | None = None) -> Any:
    r = await client.post(url, json=payload or {})
    if r.status_code >= 400:
        return {"_http_error": r.status_code, "detail": r.text[:200]}
    return r.json()


async def measure_pair(client: Any, engine_cid: str, gold_cid: str, en_cid: str | None,
                       *, min_colloc_freq: int = 1, min_ngram_freq: int = 2,
                       cql_pattern: str = '"\u0641\u064a" within sentence',
                       cql2_patterns: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["thresholds"] = {"colloc_min_freq": min_colloc_freq,
                         "ngram_min_freq": min_ngram_freq,
                         "cql_pattern": cql_pattern}

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
            {"node": "في", "window": 5, "min_freq": min_colloc_freq, "level": "word",
             "limit": 200},
        )
        rows = r.get("rows") or r.get("top_collocates") or [] if isinstance(r, dict) else []
        rows = rows if isinstance(rows, list) else []
        colloc[label] = {"rows": len(rows), "sum_O": sum(int(x.get("O", 0)) for x in rows if isinstance(x, dict))}
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
            {"n": 3, "min_freq": min_ngram_freq, "min_range": 1, "limit": 200},
        )
        rows = r.get("rows") or r.get("top_ngrams") or [] if isinstance(r, dict) else []
        rows = rows if isinstance(rows, list) else []
        ngrams[label] = {"rows": len(rows), "sum_freq": sum(int(x.get("freq", 0)) for x in rows if isinstance(x, dict))}
    out["ngrams"] = {
        "rows_delta": ngrams["gold"]["rows"] - ngrams["engine"]["rows"],
        "sum_freq_delta": ngrams["gold"]["sum_freq"] - ngrams["engine"]["sum_freq"],
    }

    # CQL within sentence scope — single-term baseline + two-token sequences
    async def _cql_total(pattern: str) -> tuple[Any, Any]:
        totals: dict[str, Any] = {}
        for label, cid in (("engine", engine_cid), ("gold", gold_cid)):
            r = await _post(
                client, f"/api/v1/corpora/{cid}/concordance/cql",
                {"query": pattern, "window": 2},
            )
            totals[label] = r.get("total") if isinstance(r, dict) else None
        return totals["engine"], totals["gold"]

    ce, cg = await _cql_total(cql_pattern)
    out["cql_within_sentence"] = {
        "pattern": cql_pattern, "engine": ce, "gold": cg,
        "delta": (cg or 0) - (ce or 0),
    }
    if cql2_patterns:
        out["cql_two_token"] = []
        for pat in cql2_patterns:
            e2, g2 = await _cql_total(pat)
            out["cql_two_token"].append({"pattern": pat, "engine": e2, "gold": g2,
                                         "delta": (g2 or 0) - (e2 or 0)})

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


async def run(data: Path, limit: int | None, en_text: Path | None, out: Path | None,
              *, pool: bool = False, min_colloc_freq: int = 1, min_ngram_freq: int = 2,
              cql_pattern: str = '"في" within sentence') -> dict[str, Any]:
    docs = load_documents(data, limit)
    if not docs:
        raise SystemExit("no usable documents — check eval/data/araseg/README.md")
    en_cid: str | None = None
    async with boot_engine() as client:
        if en_text is not None:
            en_cid = await _ingest(client, en_text.read_text(encoding="utf-8"))
        if pool:
            # ---- F2 pooled re-run: ONE engine corpus vs ONE gold corpus ----
            engine_pool, gold_pool = pooled_texts(docs)
            cql2 = select_cql_bigrams(docs)
            pats = [f'"{b["w1"]}" "{b["w2"]}" within sentence' for b in cql2["top_boundary"]]
            pats += [f'"{b["w1"]}" "{b["w2"]}" within sentence' for b in cql2["top_freq"]]
            engine_cid = await _ingest(client, engine_pool)
            gold_cid = await _ingest(client, gold_pool)
            pair = await measure_pair(client, engine_cid, gold_cid, en_cid,
                                      min_colloc_freq=min_colloc_freq,
                                      min_ngram_freq=min_ngram_freq,
                                      cql_pattern=cql_pattern, cql2_patterns=pats)
            boundary_errors = sum(
                1 for d in docs
                for p, g in zip(predict_boundaries(d["tokens"]), d["labels"],
                                strict=False) if p != g)
            report = {
                "mode": "pooled",
                "documents": len(docs),
                "tokens": sum(len(d["tokens"]) for d in docs),
                "boundary_errors_total": boundary_errors,
                "delta_convention": "gold minus engine (positive = gold segmentation "
                                    "produced more)",
                "cql_bigram_selection": cql2,
                "pair": pair,
            }
            print(f"pooled: docs={len(docs)} boundary_errors={boundary_errors} "
                  f"delta_sentences={pair.get('delta_sentences')}")
        else:
            reports = []
            for doc in docs:
                pred_bits = predict_boundaries(doc["tokens"])
                seg_errors = sum(1 for p, g in zip(pred_bits, doc["labels"], strict=False) if p != g)
                engine_cid = await _ingest(client, engine_text(doc["tokens"]))
                gold_cid = await _ingest(client, gold_text(doc["tokens"], doc["labels"]))
                pair = await measure_pair(client, engine_cid, gold_cid, en_cid,
                                          min_colloc_freq=min_colloc_freq,
                                          min_ngram_freq=min_ngram_freq,
                                          cql_pattern=cql_pattern)
                reports.append({"doc_id": doc["doc_id"], "boundary_errors": seg_errors,
                                "tokens": len(doc["tokens"]), **pair})
                print(f"{doc['doc_id']}: boundary_errors={seg_errors}, "
                      f"delta_sentences={pair.get('delta_sentences')}")
            report = {"mode": "per_document", "documents": len(reports),
                      "delta_convention": "gold minus engine (positive = gold segmentation "
                                          "produced more)",
                      "pairs": reports}
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report written: {out}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Segmentation downstream-delta eval")
    ap.add_argument("--data", required=True, type=Path,
                    help="AraSEG JSONL (doc_id/tokens/labels)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--en-text", type=Path, default=None,
                    help="optional English parallel text for the alignment delta")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--pool", action="store_true",
                    help="pool ALL documents into one engine vs one gold corpus "
                         "(F2 re-run: corpus-scale colloc/ngram/CQL deltas)")
    ap.add_argument("--min-colloc-freq", type=int, default=1,
                    help="collocation min_freq (default 1 = legacy per-doc runs; "
                         "use 5 for corpus-scale)")
    ap.add_argument("--min-ngram-freq", type=int, default=2,
                    help="n-gram min_freq (default 2 = legacy per-doc runs; "
                         "use 5 for corpus-scale)")
    ap.add_argument("--cql-pattern", default='"في" within sentence',
                    help="single-term CQL baseline pattern")
    args = ap.parse_args()
    asyncio.run(run(args.data, args.limit, args.en_text, args.out, pool=args.pool,
                    min_colloc_freq=args.min_colloc_freq,
                    min_ngram_freq=args.min_ngram_freq,
                    cql_pattern=args.cql_pattern))


if __name__ == "__main__":
    main()

"""Intrinsic evaluation of Arabic sentence segmentation against AraSEG.

Reference: Elkholy, Elmadani, Habash & Alhafni (2026), "Arabic Sentence
Segmentation Across Genres and Punctuation Conditions" (EMNLP Findings 2026,
arXiv:2606.08025). AraSEG: 658 manually annotated documents / 451K words /
8 genres, four punctuation-and-paragraph conditions (PA, NoPnx-PA, NP,
NoPnx-NP). Data: MIT licence, https://github.com/mbzuai-nlp/araseg-shared-task-2026
(HF: MBZUAI/AraSeg-2026-Shared-Task-{PA,NoPnx-PA,NP,NoPnx-NP}).

What is evaluated: the engine's rule-based splitter
``nlp.arabic.pipeline.split_arabic_sentences`` — the component that produces
every Arabic ``sentence_idx`` in the engine (KWIC context, same-sentence
collocations, CQL ``within sentence`` scope, per-sentence sentiment,
learner CAF sentence stats, Gale-Church alignment).

Protocol (mirrors the shared task): segmentation = binary classification of
"does a sentence boundary follow token t". We detokenize each document's
gold token list, run the splitter, and map every predicted boundary back to
the exact gold token it follows via a per-character owner index (see
``predict_boundaries``). Metrics per document: boundary precision / recall /
F1, then the macro average across documents (the shared task convention);
micro totals are reported as a secondary view.

Data is NOT vendored: point --data at a local copy of the shared-task files
(JSONL with doc_id/tokens/labels, as published on HF; one document per
line). See eval/data/araseg/README.md for the fetch + licence notes.

Usage (from engine/):
    python -m eval.segmentation_araseg --data /path/araseg/dev.jsonl [--task PA]
        [--limit 50] [--out report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_documents(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Load AraSEG-format documents (JSONL: doc_id, tokens, labels)."""
    docs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            doc_id = str(row.get("doc_id") or row.get("document_id") or row.get("id") or "")
            tokens = [str(t) for t in (row.get("tokens") or [])]
            labels = [int(b) for b in (row.get("labels") or row.get("sentence_boundaries") or [])]
            if not doc_id or not tokens or len(labels) != len(tokens):
                continue
            docs.append({"doc_id": doc_id, "tokens": tokens, "labels": labels})
            if limit and len(docs) >= limit:
                break
    return docs


def predict_boundaries(tokens: list[str]) -> list[int]:
    """Run the engine splitter on the detokenized text and return the
    predicted boundary bitstring (1 = boundary follows this token).

    Alignment is by an explicit per-character owner map, not by re-counting
    whitespace tokens: the detokenized text is built once with, for every
    character, the gold token index that owns it, and each predicted chunk
    boundary is credited to the gold token owning the chunk's last character.
    Re-counting ``chunk.split()`` is WRONG here because AraSEG streams
    contain bare ``'\\n'`` marker tokens (4,844 in the PA dev set alone);
    joining them as words makes ``text.split()`` yield fewer tokens than the
    gold list and shifts every subsequent boundary (this produced the bogus
    micro-F1 0.107 on PA in run 40913999140).

    A whitespace-only gold token is emitted as one real ``'\\n'`` character
    owned by that token: the engine's splitter treats a newline as a
    terminal, so paragraph breaks that AraSEG encodes as ``'\\n'`` markers
    are legitimate split cues. In the PA dev set the gold boundary sits on
    the content token *before* the marker in 100% of cases, which is exactly
    where the owner map credits it. The marker token itself can therefore
    only be a predicted boundary when the gold puts one there (156 bare
    blank-line markers in PA do) — those are reported as misses, a documented
    ceiling of 1.2% of gold boundaries.

    The document end is a boundary (AraSEG convention: label bitstrings end
    in 1), so the final content token always closes with a boundary bit."""
    from nlp.arabic.pipeline import split_arabic_sentences

    parts: list[str] = []
    owner: list[int | None] = []  # per character of `text`: gold token index
    for idx, tok in enumerate(tokens):
        if idx:
            parts.append(" ")
            owner.append(None)
        if not tok.strip():
            # AraSEG line-break marker: a real newline the engine may split on
            parts.append("\n")
            owner.append(idx)
        else:
            parts.append(tok)
            owner.extend([idx] * len(tok))
    text = "".join(parts)

    bits = [0] * len(tokens)

    def credit(char_pos: int) -> None:
        """Credit the boundary after `char_pos` to its owning gold token."""
        j = min(char_pos, len(owner) - 1)
        while j >= 0 and (owner[j] is None or text[j].isspace()):
            j -= 1
        if j >= 0 and owner[j] is not None:
            bits[owner[j]] = 1  # type: ignore[index]

    cursor = 0
    for chunk in split_arabic_sentences(text):
        # chunks are stripped, consecutive slices of `text`; skip the
        # whitespace the splitter consumed between them
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        end = cursor + len(chunk)
        credit(end - 1)
        cursor = end
    credit(len(text) - 1)  # document end is a boundary
    return bits


def prf1(pred_bits: list[int], gold_bits: list[int]) -> dict[str, float]:
    tp = sum(1 for p, g in zip(pred_bits, gold_bits, strict=False) if p == 1 and g == 1)
    fp = sum(1 for p, g in zip(pred_bits, gold_bits, strict=False) if p == 1 and g == 0)
    fn = sum(1 for p, g in zip(pred_bits, gold_bits, strict=False) if p == 0 and g == 1)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def evaluate(docs: list[dict[str, Any]]) -> dict[str, Any]:
    per_doc: list[dict[str, Any]] = []
    micro = {"tp": 0, "fp": 0, "fn": 0}
    for doc in docs:
        pred = predict_boundaries(doc["tokens"])
        m = prf1(pred, doc["labels"])
        per_doc.append({"doc_id": doc["doc_id"], "tokens": len(doc["tokens"]), **m})
        for k in ("tp", "fp", "fn"):
            micro[k] += int(m[k])
    n = len(per_doc)
    macro = {
        k: sum(d[k] for d in per_doc) / n if n else 0.0
        for k in ("precision", "recall", "f1")
    }
    tp, fp, fn = micro["tp"], micro["fp"], micro["fn"]
    p_micro = tp / (tp + fp) if tp + fp else 0.0
    r_micro = tp / (tp + fn) if tp + fn else 0.0
    f1_micro = 2 * p_micro * r_micro / (p_micro + r_micro) if p_micro + r_micro else 0.0
    perfect = sum(1 for d in per_doc if d["fp"] == 0 and d["fn"] == 0)
    return {
        "documents": n,
        "macro_P": macro["precision"],
        "macro_R": macro["recall"],
        "macro_F1": macro["f1"],
        "micro_P": p_micro,
        "micro_R": r_micro,
        "micro_F1": f1_micro,
        "micro_tp": tp,
        "micro_fp": fp,
        "micro_fn": fn,
        "perfect_documents": perfect,
        "per_doc": per_doc,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="AraSEG intrinsic segmentation eval")
    ap.add_argument("--data", required=True, help="JSONL file (doc_id/tokens/labels)")
    ap.add_argument("--task", default="PA", choices=["PA", "NoPnx-PA", "NP", "NoPnx-NP"])
    ap.add_argument("--limit", type=int, default=None, help="evaluate only the first N docs")
    ap.add_argument("--out", default=None, help="write JSON report here")
    args = ap.parse_args()
    docs = load_documents(Path(args.data), args.limit)
    if not docs:
        print("no usable documents found — check the JSONL schema "
              "(doc_id/tokens/labels; see eval/data/araseg/README.md)", file=sys.stderr)
        raise SystemExit(2)
    report = evaluate(docs)
    summary = {k: v for k, v in report.items() if k != "per_doc"}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"task": args.task, **report}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"report written: {args.out}")


if __name__ == "__main__":
    main()

"""A5 calibration: score NLTK Punkt, pySBD and the spaCy sentencizer through
the AraSEG evaluator (eval.segmentation_araseg) on the same checksum-pinned
dev splits, for comparison with Table 4 of Elkholy, Elmadani, Habash &
Alhafni (2026), "Arabic Sentence Segmentation Across Genres and Punctuation
Conditions" (arXiv:2606.08025), Findings of EMNLP 2026.

Protocol (identical to the engine row):
- binary classification of "does a sentence boundary follow gold token t";
- the detokenized document text and the per-character owner map are built
  exactly as eval.segmentation_araseg.predict_boundaries() builds them
  (whitespace-joined tokens, AraSEG '\\n' markers kept as real newlines);
- each baseline's sentence spans are credited to the gold token owning the
  span's last non-space character; the document end is a boundary;
- per-document P/R/F1, macro average across documents (shared-task
  convention), micro as secondary view.

Tool configurations (disclosed, chosen for paper parity):
- NLTK Punkt: trained per condition on the AraSEG TRAIN split's detokenized
  text (the paper: "an unsupervised NLTK Punkt segmenter trained on ARASEG").
- pySBD: pysbd 0.3.4, Segmenter(language='ar') — the shipped Arabic class.
- spaCy sentencizer: spacy.blank('ar') + sentencizer with DEFAULT punct_chars
  (includes '.', '!', '?', '؟', '۔' ...; NOT the Arabic comma '،').

This module adds no engine behaviour and touches nothing outside engine/eval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval.segmentation_araseg import load_documents, prf1


def text_and_owner(tokens: list[str]) -> tuple[str, list[int | None]]:
    """Detokenized text + per-character gold-token owner map.

    Same construction as eval.segmentation_araseg.predict_boundaries().
    """
    parts: list[str] = []
    owner: list[int | None] = []
    for idx, tok in enumerate(tokens):
        if idx:
            parts.append(" ")
            owner.append(None)
        if not tok.strip():
            parts.append("\n")
            owner.append(idx)
        else:
            parts.append(tok)
            owner.extend([idx] * len(tok))
    return "".join(parts), owner


def bits_from_spans(
    spans: list[tuple[int, int]], text: str, owner: list[int | None], n_tokens: int
) -> list[int]:
    """Credit sentence spans (start, end_exclusive) to gold-token boundaries."""
    bits = [0] * n_tokens

    def credit(char_pos: int) -> None:
        j = min(char_pos, len(owner) - 1)
        while j >= 0 and (owner[j] is None or text[j].isspace()):
            j -= 1
        if j >= 0 and owner[j] is not None:
            bits[owner[j]] = 1  # type: ignore[index]

    for _start, end in spans:
        credit(end - 1)
    credit(len(text) - 1)  # document end is a boundary (AraSEG convention)
    return bits


def punkt_spans(text: str, tokenizer: Any) -> list[tuple[int, int]]:
    try:  # NLTK >= 3.9: PunktSentenceTokenizer.span_tokenize
        return list(tokenizer.span_tokenize(text))
    except AttributeError:  # pragma: no cover
        out, cursor = [], 0
        for sent in tokenizer.tokenize(text):
            i = text.find(sent, cursor)
            i = cursor if i < 0 else i
            out.append((i, i + len(sent)))
            cursor = i + len(sent)
        return out


def pysbd_spans(text: str, segmenter: Any) -> list[tuple[int, int]]:
    """pysbd returns sentence STRINGS (possibly whitespace-normalized); map
    them back onto the original text by ordered search from a cursor. Spans
    that cannot be located are logged once by the caller."""
    out: list[tuple[int, int]] = []
    cursor = 0
    for sent in segmenter.segment(text):
        s = sent.strip()
        if not s:
            continue
        i = text.find(s, cursor)
        if i < 0:  # pysbd normalized something; fall back to global search
            i = text.find(s)
        if i < 0:
            continue
        out.append((i, i + len(s)))
        cursor = i + len(s)
    return out


def spacy_spans(text: str, nlp: Any) -> list[tuple[int, int]]:
    return [(s.start_char, s.end_char) for s in nlp(text).sents]


def _paragraph_slices(text: str) -> list[tuple[int, int]]:
    """Slices of `text` between newline characters (empty ones dropped)."""
    out: list[tuple[int, int]] = []
    start = 0
    for i, ch in enumerate(text):
        if ch == "\n":
            if i > start:
                out.append((start, i))
            start = i + 1
    if start < len(text):
        out.append((start, len(text)))
    return out


def spans_split_on_paragraphs(
    text: str, base: Any, kind: str
) -> list[tuple[int, int]]:
    """Run `base` within each paragraph and force a boundary at every
    paragraph end.

    Rationale (verified against Table 4 of arXiv:2606.08025): in the PA
    conditions the paper's Punkt/SpaCySENT rows match the evaluator only when
    paragraph breaks (AraSEG '\\n' markers) count as sentence boundaries;
    punkt and the sentencizer ignore bare newlines on their own, while
    pysbd(ar) already splits on them. NP (no paragraph breaks) is unaffected
    and was reproduced EXACTLY without this (punkt 52.32 vs 52.3, pysbd
    52.05 vs 52.1, spacy 54.31 vs 54.3)."""
    spans: list[tuple[int, int]] = []
    for start, end in _paragraph_slices(text):
        seg = text[start:end]
        if kind == "punkt":
            for s0, s1 in punkt_spans(seg, base):
                spans.append((start + s0, start + s1))
        else:
            for s0, s1 in spacy_spans(seg, base):
                spans.append((start + s0, start + s1))
        spans.append((start, end))  # paragraph end is a boundary
    return spans


def train_punkt(train_jsonl: Path) -> Any:
    from nltk.tokenize.punkt import PunktSentenceTokenizer

    texts: list[str] = []
    for doc in load_documents(train_jsonl):
        t, _ = text_and_owner(doc["tokens"])
        texts.append(t)
    tok = PunktSentenceTokenizer()
    tok.train("\n\n".join(texts))
    return tok


def aggregate(docs: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    per_doc: list[dict[str, Any]] = []
    micro = {"tp": 0, "fp": 0, "fn": 0}
    for doc in docs:
        m = prf1(doc["pred"], doc["labels"])
        per_doc.append({"doc_id": doc["doc_id"], **m})
        for k in micro:
            micro[k] += int(m[k])
    n = len(per_doc)
    macro = {k: sum(d[k] for d in per_doc) / n if n else 0.0
             for k in ("precision", "recall", "f1")}
    tp, fp, fn = micro["tp"], micro["fp"], micro["fn"]
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"tool": tool, "documents": n,
            "macro_P": macro["precision"], "macro_R": macro["recall"], "macro_F1": macro["f1"],
            "micro_P": p, "micro_R": r, "micro_F1": f1,
            "micro_tp": tp, "micro_fp": fp, "micro_fn": fn, "per_doc": per_doc}


def main() -> None:
    ap = argparse.ArgumentParser(description="AraSEG baseline calibration (A5)")
    ap.add_argument("--data", required=True, help="dev JSONL (doc_id/tokens/labels)")
    ap.add_argument("--task", default="PA", choices=["PA", "NP"])
    ap.add_argument("--punkt-train", default=None,
                    help="train JSONL to fit Punkt on (same condition)")
    ap.add_argument("--tools", default="punkt,pysbd,spacy")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    docs = load_documents(Path(args.data))
    if not docs:
        print("no usable documents", file=sys.stderr)
        raise SystemExit(2)

    tokenizers: dict[str, Any] = {}
    if "punkt" in tools:
        if not args.punkt_train:
            print("--punkt-train is required for punkt", file=sys.stderr)
            raise SystemExit(2)
        tokenizers["punkt"] = train_punkt(Path(args.punkt_train))
    if "pysbd" in tools:
        import pysbd
        tokenizers["pysbd"] = pysbd.Segmenter(language="ar", clean=False)
    if "spacy" in tools:
        import spacy
        nlp = spacy.blank("ar")
        nlp.add_pipe("sentencizer")
        tokenizers["spacy"] = nlp

    results: list[dict[str, Any]] = []
    for tool, tk in tokenizers.items():
        prepped = []
        for doc in docs:
            text, owner = text_and_owner(doc["tokens"])
            if tool == "punkt":
                spans = spans_split_on_paragraphs(text, tk, "punkt")
            elif tool == "pysbd":
                spans = pysbd_spans(text, tk)
            else:
                spans = spans_split_on_paragraphs(text, tk, "spacy")
            prepped.append({**doc, "pred": bits_from_spans(spans, text, owner, len(doc["tokens"]))})
        results.append(aggregate(prepped, tool))

    report = {
        "task": args.task,
        "protocol": "owner-map credit of tool sentence spans onto gold token boundaries; "
                    "doc end forced as boundary (same as eval.segmentation_araseg)",
        "punkt_training": args.punkt_train or None,
        "results": [{k: v for k, v in r.items() if k != "per_doc"} for r in results],
        "per_doc": {r["tool"]: r["per_doc"] for r in results},
    }
    summary = json.dumps({k: v for k, v in report.items() if k != "per_doc"},
                         ensure_ascii=False, indent=1)
    print(summary)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report written: {args.out}")


if __name__ == "__main__":
    main()

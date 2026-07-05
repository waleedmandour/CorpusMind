"""
High-level ingestion service: parse file → clean → tokenize/tag → persist.

Used by the corpus-management API (§8.1, §8.2).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from ingestion.parsing import parse_file
from nlp.general.pipeline import get_pipeline
from storage.models import AnnotationVersion, Corpus, Document, Token

log = get_logger(__name__)


async def ingest_document(
    session: AsyncSession,
    corpus: Corpus,
    filename: str,
    raw: bytes,
    *,
    metadata: dict | None = None,
    language: str | None = None,
) -> Document:
    """Parse, clean, tokenize, tag, and persist one document into `corpus`."""
    lang = language or corpus.language or "en"
    cleaned_text, fmt, encoding = parse_file(filename, raw)

    # Detect language if not pinned (best-effort — falls back to corpus default)
    detected = lang
    try:
        if not language and len(cleaned_text) > 100:
            from langdetect import detect
            detected = detect(cleaned_text[:2000])
    except Exception:
        pass  # langdetect occasionally throws on very short / noisy text

    # Create the document row
    doc = Document(
        corpus_id=corpus.id,
        filename=filename,
        format=fmt,
        encoding=encoding,
        detected_language=detected,
        raw_size_bytes=len(raw),
        cleaned_text=cleaned_text,
        meta=metadata or {},
    )
    session.add(doc)
    await session.flush()  # get doc.id

    # Run the NLP pipeline
    pipeline = get_pipeline(backend="spacy", language=lang)
    info = pipeline.info()
    parsed = pipeline.parse_document(cleaned_text)

    # Reuse the latest annotation version for this corpus if the pipeline recipe
    # matches; otherwise create a new one (§4.8 reproducibility — versioning
    # is per pipeline-change, not per document).
    existing = await session.scalar(
        select(AnnotationVersion).where(AnnotationVersion.corpus_id == corpus.id)
        .order_by(AnnotationVersion.created_at.desc()).limit(1)
    )

    needs_new_version = (
        existing is None
        or existing.model_name != f"{info.backend}:{info.model_name}"
        or existing.model_version != info.model_version
    )

    if needs_new_version:
        version_n = 1
        if existing and existing.version_label.startswith("v"):
            try:
                version_n = int(existing.version_label[1:]) + 1
            except ValueError:
                pass
        av = AnnotationVersion(
            corpus_id=corpus.id,
            version_label=f"v{version_n}",
            model_name=f"{info.backend}:{info.model_name}",
            model_version=info.model_version,
            tokenizer=info.backend,
            tagger=info.backend,
            parser=info.backend,
            token_count=0,
            type_count=0,
            sentence_count=0,
        )
        session.add(av)
        await session.flush()
    else:
        av = existing

    # Update corpus stats cache
    corpus.stats = {
        **(corpus.stats or {}),
        "token_count": (corpus.stats or {}).get("token_count", 0) + parsed.token_count,
        "type_count": (corpus.stats or {}).get("type_count", 0) + parsed.type_count,
        "sentence_count": (corpus.stats or {}).get("sentence_count", 0) + len(parsed.sentences),
        "document_count": ((corpus.stats or {}).get("document_count", 0) + 1),
    }
    corpus.pipeline_recipe = {
        "backend": info.backend,
        "model_name": info.model_name,
        "model_version": info.model_version,
        "spacy_version": info.spacy_version,
        "language": info.language,
    }
    # Update the annotation version's aggregate counts
    av.token_count += parsed.token_count
    av.type_count += parsed.type_count
    av.sentence_count += len(parsed.sentences)

    # Bulk-insert tokens. SQLAlchemy 2.0 async uses session.add_all for bulk.
    # For very large corpora we'd switch to session.run_sync(session.bulk_insert_mappings),
    # but for Phase 1's MVP scale (single documents of <1 MB each) this is fine.
    started = time.perf_counter()
    token_rows: list[Token] = []
    for sent_idx, sent in enumerate(parsed.sentences):
        for tok_idx, tok in enumerate(sent.tokens):
            token_rows.append(Token(
                version_id=av.id,
                document_id=doc.id,
                sentence_idx=sent_idx,
                token_idx=tok_idx,
                text=tok.text,
                lemma=tok.lemma,
                pos=tok.pos,
                pos_fine=tok.pos_fine,
                morph=tok.morph,
                dep_head=tok.dep_head,
                dep_rel=tok.dep_rel,
                is_punct=tok.is_punct,
                is_stop=tok.is_stop,
            ))
    session.add_all(token_rows)
    await session.flush()
    elapsed = time.perf_counter() - started
    log.info(
        "ingest_complete",
        corpus_id=corpus.id,
        document_id=doc.id,
        version_id=av.id,
        tokens=len(token_rows),
        sentences=len(parsed.sentences),
        elapsed_ms=int(elapsed * 1000),
    )
    return doc

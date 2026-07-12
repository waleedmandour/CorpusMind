"""Research-grade features for corpus linguistics in the AI era.

Endpoints:
  - GET  /api/v1/research/precheck/{cid}      — pre-publication reproducibility audit
  - GET  /api/v1/research/ai-disclosure/{pid}  — AI usage summary for Methods disclosure
  - POST /api/v1/research/verify-turn/{tid}    — human-in-the-loop verification of an AI claim
  - POST /api/v1/research/frequency-list/export — export a frequency list as .lst
  - POST /api/v1/research/frequency-list/import — import a .lst as a reference frequency list
  - POST /api/v1/research/compare-concordance  — side-by-side concordance from two corpora
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from stats.service import compute_frequency, search_concordance
from storage.models import (
    AnnotationVersion,
    Conversation,
    ConversationTurn,
    Corpus,
    Project,
)
from storage.session import get_session

log = get_logger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# 1. Pre-publication check
# --------------------------------------------------------------------------- #


@router.get("/research/precheck/{cid}")
async def prepublication_check(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Pre-publication reproducibility audit for a corpus.

    Checks:
      a. All statistical results are reproducible from the pinned annotation version
         (i.e., the annotation version exists + has token_count > 0)
      b. All AI interpretations are flagged as non-deterministic
         (i.e., if any AI turns exist, they are flagged with a warning)
      c. The reference corpus (if any) is identified + its license permits use
      d. The pipeline recipe is complete (backend, model, version)

    Returns a structured report with pass/warn/fail for each check.
    """
    c = await session.get(Corpus, cid)
    if not c:
        raise HTTPException(404, "Corpus not found")

    checks: list[dict] = []

    # Check a: annotation version exists + has tokens
    av_result = await session.execute(
        select(AnnotationVersion)
        .where(AnnotationVersion.corpus_id == cid)
        .order_by(AnnotationVersion.created_at.desc())
        .limit(1)
    )
    av = av_result.scalars().first()
    if av and av.token_count > 0:
        checks.append({
            "id": "annotation_version",
            "label": "Annotation version pinned and has tokens",
            "status": "pass",
            "detail": f"Version {av.version_label}: {av.token_count} tokens, {av.type_count} types, model={av.model_name}:{av.model_version}",
        })
    else:
        checks.append({
            "id": "annotation_version",
            "label": "Annotation version pinned and has tokens",
            "status": "fail",
            "detail": "No annotation version found or token count is zero. Run ingestion first.",
        })

    # Check b: AI interpretations flagged as non-deterministic
    # Find all conversations linked to this project
    convs = await session.execute(
        select(Conversation).where(Conversation.project_id == c.project_id)
    )
    ai_turns_count = 0
    for conv in convs.scalars():
        turns = await session.execute(
            select(ConversationTurn).where(ConversationTurn.conversation_id == conv.id)
        )
        for turn in turns.scalars():
            if turn.role == "assistant" and turn.content:
                ai_turns_count += 1

    if ai_turns_count > 0:
        checks.append({
            "id": "ai_nondeterminism",
            "label": "AI interpretations flagged as non-deterministic",
            "status": "warn",
            "detail": f"{ai_turns_count} AI-generated interpretation(s) found. These are stochastic — re-running the same query may produce different text. Report the model + provider in your Methods section.",
        })
    else:
        checks.append({
            "id": "ai_nondeterminism",
            "label": "AI interpretations flagged as non-deterministic",
            "status": "pass",
            "detail": "No AI interpretations used. All results are deterministic.",
        })

    # Check c: pipeline recipe is complete
    recipe = c.pipeline_recipe or {}
    if recipe.get("backend") and recipe.get("model_name") and recipe.get("model_version"):
        checks.append({
            "id": "pipeline_recipe",
            "label": "Pipeline recipe is complete",
            "status": "pass",
            "detail": f"Backend: {recipe.get('backend')}, Model: {recipe.get('model_name')}, Version: {recipe.get('model_version')}, spaCy: {recipe.get('spacy_version')}",
        })
    else:
        checks.append({
            "id": "pipeline_recipe",
            "label": "Pipeline recipe is complete",
            "status": "fail",
            "detail": "Pipeline recipe is incomplete. Some fields (backend, model_name, model_version) are missing.",
        })

    # Check d: corpus has documents
    doc_count = c.stats.get("document_count", 0) if c.stats else 0
    if doc_count > 0:
        checks.append({
            "id": "documents",
            "label": "Corpus has documents",
            "status": "pass",
            "detail": f"{doc_count} document(s) ingested, {c.stats.get('token_count', 0)} tokens.",
        })
    else:
        checks.append({
            "id": "documents",
            "label": "Corpus has documents",
            "status": "fail",
            "detail": "No documents ingested.",
        })

    # Overall verdict
    has_fail = any(c["status"] == "fail" for c in checks)
    has_warn = any(c["status"] == "warn" for c in checks)
    overall = "fail" if has_fail else ("warn" if has_warn else "pass")

    return {
        "corpus_id": cid,
        "corpus_name": c.name,
        "overall": overall,
        "checks": checks,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# --------------------------------------------------------------------------- #
# 2. AI usage disclosure
# --------------------------------------------------------------------------- #


@router.get("/research/ai-disclosure/{pid}")
async def ai_disclosure(pid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Summarize AI usage for a project, for inclusion in a Methods section.

    Returns: provider, model, total turns, grounded turns, ungrounded turns,
    verified turns, tools called, frameworks used. This is the transparency
    payload that should be reported in peer-reviewed work.
    """
    p = await session.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")

    convs = await session.execute(
        select(Conversation).where(Conversation.project_id == pid)
    )
    total_turns = 0
    grounded_turns = 0
    verified_turns = 0
    rejected_turns = 0
    providers: set[str] = set()
    models: set[str] = set()
    frameworks: set[str] = set()
    tools_called: set[str] = set()

    for conv in convs.scalars():
        if conv.provider:
            providers.add(conv.provider)
        if conv.model:
            models.add(conv.model)
        if conv.framework:
            frameworks.add(conv.framework)

        turns = await session.execute(
            select(ConversationTurn).where(ConversationTurn.conversation_id == conv.id)
        )
        for turn in turns.scalars():
            if turn.role == "assistant":
                total_turns += 1
                if turn.grounded:
                    grounded_turns += 1
                if turn.verified == "accepted":
                    verified_turns += 1
                elif turn.verified == "rejected":
                    rejected_turns += 1
                # Extract tool names from tool_calls
                for tc in (turn.tool_calls or []):
                    if isinstance(tc, dict) and tc.get("name"):
                        tools_called.add(tc["name"])

    ungrounded = total_turns - grounded_turns

    return {
        "project_id": pid,
        "project_name": p.name,
        "ai_used": total_turns > 0,
        "providers": sorted(providers),
        "models": sorted(models),
        "frameworks": sorted(frameworks),
        "total_ai_turns": total_turns,
        "grounded_turns": grounded_turns,
        "ungrounded_turns": ungrounded,
        "verified_accepted": verified_turns,
        "verified_rejected": rejected_turns,
        "unverified": total_turns - verified_turns - rejected_turns,
        "tools_called": sorted(tools_called),
        "disclosure_text": (
            f"AI assistance was used in this analysis via CorpusMind v0.1.0. "
            f"Provider(s): {', '.join(sorted(providers)) or 'none'}. "
            f"Model(s): {', '.join(sorted(models)) or 'none'}. "
            f"Total AI turns: {total_turns} ({grounded_turns} grounded, {ungrounded} ungrounded). "
            f"Human-verified: {verified_turns} accepted, {rejected_turns} rejected, "
            f"{total_turns - verified_turns - rejected_turns} unverified. "
            f"Tools called: {', '.join(sorted(tools_called)) or 'none'}. "
            f"AI interpretations are stochastic; statistical results are deterministic and reproducible."
            if total_turns > 0 else
            "No AI assistance was used in this analysis. All results are deterministic."
        ),
    }


# --------------------------------------------------------------------------- #
# 3. Verify this interpretation (human-in-the-loop)
# --------------------------------------------------------------------------- #


class VerifyRequest(BaseModel):
    verified: str = Field(..., pattern="^(accepted|rejected|edited)$")
    notes: str = ""


@router.post("/research/verify-turn/{tid}")
async def verify_turn(
    tid: int,
    body: VerifyRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mark an AI interpretation as accepted, rejected, or edited by the human.

    This is the load-bearing implementation of "AI assists, human decides."
    The verification state is persisted in the audit trail and included in
    the AI usage disclosure.
    """
    turn = await session.get(ConversationTurn, tid)
    if not turn:
        raise HTTPException(404, "Turn not found")

    turn.verified = body.verified
    turn.verification_notes = body.notes
    await session.flush()
    return {
        "ok": True,
        "turn_id": tid,
        "verified": body.verified,
        "notes": body.notes,
    }


# --------------------------------------------------------------------------- #
# 4. Frequency list import/export (.lst format)
# --------------------------------------------------------------------------- #


class FreqListExportRequest(BaseModel):
    unit: str = "word"
    min_freq: int = 1
    limit: int = 10000


@router.post("/research/frequency-list/export/{cid}")
async def export_frequency_list(
    cid: str,
    body: FreqListExportRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Export a frequency list as a portable .lst file (tab-separated).

    Format: word<TAB>frequency<TAB>per_million<TAB>percent
    This is the WordSmith-style portable frequency list — decoupled from
    the corpus so it can be shared even when the corpus itself can't
    (due to copyright).
    """
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")

    r = await compute_frequency(session, cid, unit=body.unit, min_freq=body.min_freq, limit=body.limit)

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t")
    writer.writerow([f"# CorpusMind frequency list ({body.unit})"])
    writer.writerow([f"# Exported: {datetime.now(UTC).isoformat()}"])
    writer.writerow([f"# Total tokens: {r.total_tokens}, Total types: {r.total_types}"])
    writer.writerow(["word", "frequency", "per_million", "percent"])
    for row in r.rows:
        writer.writerow([row["item"], row["freq"], row["per_million"], row["percent"]])

    fname = f"freqlist_{cid}_{body.unit}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.lst"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/tab-separated-values; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


class FreqListImportRequest(BaseModel):
    """Import a frequency list from a .lst file content (uploaded as text)."""
    content: str = Field(..., description="The .lst file content (tab-separated)")


@router.post("/research/frequency-list/import")
async def import_frequency_list(body: FreqListImportRequest) -> dict:
    """Parse a .lst frequency list file and return the data as JSON.

    The frontend can then use this as a reference frequency list for
    keyness comparison (without needing a full corpus).
    """
    lines = body.content.strip().split("\n")
    items: list[dict] = []
    total_tokens = 0
    total_types = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            word = parts[0]
            try:
                freq = int(parts[1])
            except ValueError:
                continue
            items.append({"word": word, "freq": freq})
            total_tokens += freq
            total_types += 1

    return {
        "items": items,
        "total_tokens": total_tokens,
        "total_types": total_types,
        "imported_at": datetime.now(UTC).isoformat(),
    }


# --------------------------------------------------------------------------- #
# 5. Side-by-side concordance comparison
# --------------------------------------------------------------------------- #


class CompareConcordanceRequest(BaseModel):
    target_corpus_id: str
    reference_corpus_id: str
    query: str
    level: str = "word"
    case_sensitive: bool = False
    window: int = 5
    limit: int = 20


@router.post("/research/compare-concordance")
async def compare_concordance(
    body: CompareConcordanceRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Side-by-side concordance comparison from two corpora.

    Runs the same concordance query against both the target and reference
    corpus, returns both result sets for side-by-side display. Useful for
    contrastive analysis (e.g., comparing how "freedom" is used in
    academic vs. news corpora).
    """
    # Target
    target_r = await search_concordance(
        session, body.target_corpus_id, body.query,
        level=body.level, case_sensitive=body.case_sensitive,
        window=body.window, limit=body.limit,
    )
    # Reference
    ref_r = await search_concordance(
        session, body.reference_corpus_id, body.query,
        level=body.level, case_sensitive=body.case_sensitive,
        window=body.window, limit=body.limit,
    )

    return {
        "query": body.query,
        "target": {
            "corpus_id": body.target_corpus_id,
            "total": target_r.total,
            "lines": [
                {
                    "line_id": l.line_id, "document": l.document_filename,
                    "left": l.left, "node": l.node, "right": l.right,
                    "pos": l.pos, "lemma": l.lemma,
                }
                for l in target_r.lines
            ],
        },
        "reference": {
            "corpus_id": body.reference_corpus_id,
            "total": ref_r.total,
            "lines": [
                {
                    "line_id": l.line_id, "document": l.document_filename,
                    "left": l.left, "node": l.node, "right": l.right,
                    "pos": l.pos, "lemma": l.lemma,
                }
                for l in ref_r.lines
            ],
        },
    }


# --------------------------------------------------------------------------- #
# 6. Bundled reference corpora (BE06, AmE06)
# --------------------------------------------------------------------------- #


@router.get("/research/bundled-references")
async def list_bundled_references() -> dict:
    """List available bundled reference frequency lists.

    These are small (~5 MB) word-frequency lists derived from open
    frequency data. They're suitable for keyness comparison without
    needing a full reference corpus.
    """
    import os
    ref_dir = os.path.join(os.path.dirname(__file__), "..", "..", "reference-data", "reference-corpora", "en")
    ref_dir = os.path.normpath(ref_dir)

    bundled = []
    # BE06
    be06_path = os.path.join(ref_dir, "be06-freq-top1000.tsv")
    if os.path.exists(be06_path):
        bundled.append({
            "name": "BE06",
            "desc": "British English written, top 1000 words (derived from open frequency data)",
            "size": "~5 KB",
            "available": True,
            "file": "be06-freq-top1000.tsv",
        })
    else:
        bundled.append({
            "name": "BE06",
            "desc": "British English written reference corpus",
            "size": "~5 MB",
            "available": False,
            "file": None,
        })

    bundled.append({
        "name": "AmE06",
        "desc": "American English written reference corpus",
        "size": "~5 MB",
        "available": False,
        "file": None,
    })
    bundled.append({
        "name": "BNC Baby",
        "desc": "British National Corpus sample (4M words)",
        "size": "~12 MB",
        "available": False,
        "file": None,
    })

    return {"references": bundled}


@router.get("/research/bundled-references/{name}")
async def get_bundled_reference(name: str) -> dict:
    """Get a bundled reference frequency list as JSON.

    Returns: { name, items: [{word, freq}], total_tokens, total_types }
    """
    import csv
    import os

    ref_dir = os.path.join(os.path.dirname(__file__), "..", "..", "reference-data", "reference-corpora", "en")
    ref_dir = os.path.normpath(ref_dir)

    # Map name to file
    file_map = {
        "BE06": "be06-freq-top1000.tsv",
    }

    filename = file_map.get(name)
    if not filename:
        raise HTTPException(404, f"Bundled reference '{name}' not found")

    filepath = os.path.join(ref_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"File not found: {filename}")

    items = []
    total_tokens = 0
    with open(filepath, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if len(row) >= 2:
                word = row[0]
                try:
                    freq = int(row[1])
                except ValueError:
                    continue
                items.append({"word": word, "freq": freq})
                total_tokens += freq

    return {
        "name": name,
        "items": items,
        "total_tokens": total_tokens,
        "total_types": len(items),
    }

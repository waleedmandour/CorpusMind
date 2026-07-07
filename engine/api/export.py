"""Export endpoints: Excel + PDF (§8.23, §8.20)."""
from __future__ import annotations

import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from stats.service import (
    compute_collocations,
    compute_frequency,
    compute_keyness,
    search_concordance,
)
from storage.models import Corpus
from storage.session import get_session

router = APIRouter()


class ExportConcordanceRequest(BaseModel):
    query: str
    level: str = "word"
    case_sensitive: bool = False
    window: int = 5
    limit: int = 1000


class ExportFrequencyRequest(BaseModel):
    unit: str = "word"
    min_freq: int = 1
    limit: int = 1000


class ExportCollocationRequest(BaseModel):
    node: str
    level: str = "word"
    window: int = 5
    min_freq: int = 3
    measures: list[str] | None = None
    limit: int = 500


class ExportKeynessRequest(BaseModel):
    reference_corpus_id: str
    min_freq: int = 5
    limit: int = 500


# --------------------------------------------------------------------------- #
# Excel (openpyxl)
# --------------------------------------------------------------------------- #


def _xlsx_stream(sheet_name: str, headers: list[str], rows: list[list]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]  # Excel limit
    ws.append(headers)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0B6E4F", end_color="0B6E4F", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="left", vertical="center")
    for r in rows:
        ws.append(r)
    # Auto-size columns (approximate)
    for i, h in enumerate(headers, start=1):
        max_len = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:100] if i - 1 < len(r)])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max_len + 2, 60)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.post("/corpora/{cid}/export/concordance.xlsx")
async def export_concordance_xlsx(cid: str, body: ExportConcordanceRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await search_concordance(
        session, cid, body.query, level=body.level,
        case_sensitive=body.case_sensitive, window=body.window, limit=body.limit,
    )
    headers = ["Line ID", "Document", "Sentence", "Token Idx", "Left Context", "Node", "Right Context", "POS", "Lemma"]
    rows = [[l.line_id, l.document_filename, l.sentence_idx, l.token_idx, l.left, l.node, l.right, l.pos, l.lemma] for l in r.lines]
    data = _xlsx_stream("Concordance", headers, rows)
    fname = f"concordance_{cid}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/corpora/{cid}/export/frequency.xlsx")
async def export_frequency_xlsx(cid: str, body: ExportFrequencyRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_frequency(session, cid, unit=body.unit, min_freq=body.min_freq, limit=body.limit)
    headers = [body.unit.capitalize(), "Frequency", "Per Million", "Percent"]
    rows = [[row["item"], row["freq"], row["per_million"], row["percent"]] for row in r.rows]
    data = _xlsx_stream(f"Frequency ({body.unit})", headers, rows)
    fname = f"frequency_{cid}_{body.unit}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/corpora/{cid}/export/collocations.xlsx")
async def export_collocations_xlsx(cid: str, body: ExportCollocationRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_collocations(
        session, cid, body.node, level=body.level, window=body.window,
        min_freq=body.min_freq, measures=body.measures, limit=body.limit,
    )
    # Determine headers from the first row (measures vary)
    headers = ["Collocate", "O", "f(node)", "f(collocate)", "N"]
    if r.rows:
        extra_keys = [k for k in r.rows[0].keys() if k not in {"collocate", "O", "fx", "fy", "N"}]
        headers.extend(extra_keys)
    rows = []
    for row in r.rows:
        rows.append([row.get("collocate"), row.get("O"), row.get("fx"), row.get("fy"), row.get("N")] +
                    [row.get(k) for k in headers[5:]])
    data = _xlsx_stream(f"Collocations ({body.node})", headers, rows)
    fname = f"collocations_{cid}_{body.node}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/corpora/{cid}/export/keyness.xlsx")
async def export_keyness_xlsx(cid: str, body: ExportKeynessRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Target corpus not found")
    r = await compute_keyness(session, cid, body.reference_corpus_id, min_freq=body.min_freq, limit=body.limit)
    headers = ["Term", "f1 (target)", "f2 (ref)", "LL", "Chi²", "Log Ratio", "%DIFF", "Simple Maths", "Odds Ratio", "Direction"]
    rows = []
    for row in r.positive_keywords[:body.limit]:
        rows.append([row["term"], row["f1"], row["f2"],
                     row.get("log_likelihood"), row.get("chi_square"),
                     row.get("log_ratio"), row.get("pct_diff"),
                     row.get("simple_maths"), row.get("odds_ratio"), "positive"])
    for row in r.negative_keywords[:body.limit]:
        rows.append([row["term"], row["f1"], row["f2"],
                     row.get("log_likelihood"), row.get("chi_square"),
                     row.get("log_ratio"), row.get("pct_diff"),
                     row.get("simple_maths"), row.get("odds_ratio"), "negative"])
    data = _xlsx_stream("Keyness", headers, rows)
    fname = f"keyness_{cid}_vs_{body.reference_corpus_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# --------------------------------------------------------------------------- #
# PDF (reportlab) — methods section auto-draft (§8.23)
# --------------------------------------------------------------------------- #


@router.get("/corpora/{cid}/methods.pdf")
async def export_methods_pdf(cid: str, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    """Auto-draft a methodology paragraph (§8.23) for the corpus's pipeline recipe."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    c = await session.get(Corpus, cid)
    if not c:
        raise HTTPException(404, "Corpus not found")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=colors.HexColor("#0B6E4F"))
    body = ParagraphStyle("Body", parent=styles["BodyText"], alignment=TA_LEFT, leading=15)
    recipe = c.pipeline_recipe or {}
    stats = c.stats or {}

    flow = [
        Paragraph("Methods Section (auto-drafted)", h1),
        Spacer(1, 12),
        Paragraph(
            f"The analysis was conducted using <b>CorpusMind</b> v0.1.0. "
            f"The corpus &ldquo;{c.name}&rdquo; ({c.language}) contained "
            f"{stats.get('document_count', 0)} documents, "
            f"{stats.get('token_count', 0)} tokens, and "
            f"{stats.get('type_count', 0)} types. "
            f"Texts were tokenized and annotated using "
            f"<b>{recipe.get('backend', 'spacy')}</b> with the "
            f"<b>{recipe.get('model_name', 'en_core_web_sm')}</b> model "
            f"(version {recipe.get('model_version', 'unknown')}; "
            f"spaCy {recipe.get('spacy_version', 'unknown')}). "
            f"Annotation versions are pinned per corpus for reproducibility.",
            body,
        ),
        Spacer(1, 18),
        Paragraph("Statistical measures", h1),
        Spacer(1, 6),
        Paragraph(
            "Collocation strength was computed using Mutual Information (Church &amp; Hanks, 1990), "
            "T-score, log-likelihood (Dunning, 1993), Dice, LogDice (Rychlý, 2008), chi-square, "
            "and Delta P (Gries, 2013; Ellis, 2007). Keyness was computed using log-likelihood "
            "and chi-square as significance tests, with Log Ratio (Hardie, 2014), %DIFF "
            "(Gabrielatos &amp; Marchi, 2012), Simple Maths (Kilgarriff, 2009), and Odds Ratio "
            "as effect-size measures. Dispersion was computed using Juilland's D and Gries' DP "
            "(Gries, 2008). Standardized type-token ratio (STTR) was computed over 1000-token "
            "chunks. All formulas are documented in <i>docs/METHODOLOGY.md</i>.",
            body,
        ),
        Spacer(1, 18),
        Paragraph("Reproducibility", h1),
        Spacer(1, 6),
        Paragraph(
            "Every analysis result is traceable to the exact annotation version, model, and "
            "formula version that produced it. The pipeline recipe recorded for this corpus is: "
            f"{recipe}.",
            body,
        ),
    ]
    doc.build(flow)
    data = buf.getvalue()
    fname = f"methods_{cid}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})

"""Generate the CorpusMind User Guide PDF using ReportLab.
Style adapted from the RDAT Translation Copilot user guide (v0.2.0).
"""
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether,
    Table, TableStyle, ListFlowable, ListItem, HRFlowable, Image as RLImage
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

# ---- Font registration ----
FONT_DIR = "/usr/share/fonts/truetype"
pdfmetrics.registerFont(TTFont("BodySerif", f"{FONT_DIR}/liberation/LiberationSerif-Regular.ttf"))
pdfmetrics.registerFont(TTFont("BodySerif-Bold", f"{FONT_DIR}/liberation/LiberationSerif-Bold.ttf"))
pdfmetrics.registerFont(TTFont("BodySerif-Italic", f"{FONT_DIR}/liberation/LiberationSerif-Italic.ttf"))
registerFontFamily("BodySerif", normal="BodySerif", bold="BodySerif-Bold", italic="BodySerif-Italic")

pdfmetrics.registerFont(TTFont("HeadSans", f"{FONT_DIR}/liberation/LiberationSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("HeadSans-Bold", f"{FONT_DIR}/liberation/LiberationSans-Bold.ttf"))
registerFontFamily("HeadSans", normal="HeadSans", bold="HeadSans-Bold")

pdfmetrics.registerFont(TTFont("LibMono", f"{FONT_DIR}/liberation/LiberationMono-Regular.ttf"))
pdfmetrics.registerFont(TTFont("LibMono-Bold", f"{FONT_DIR}/liberation/LiberationMono-Bold.ttf"))
registerFontFamily("LibMono", normal="LibMono", bold="LibMono-Bold")

# Arabic font (for the Arabic user guide)
import os
arabic_font_path = "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf"
# Try to find a proper Arabic font
for candidate in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]:
    if os.path.exists(candidate):
        pdfmetrics.registerFont(TTFont("ArabicBody", candidate))
        break

# ---- Colors (matching rdat theme) ----
BRAND = HexColor("#0b6e4f")
BRAND_DARK = HexColor("#095c41")
BRAND_LIGHT = HexColor("#e8f5e9")
ACCENT = HexColor("#e8b339")
TEXT = HexColor("#1a1a2e")
TEXT_MUTED = HexColor("#555555")
BG_SUBTLE = HexColor("#f5f5f5")
CODE_BG = HexColor("#eef0ee")
BORDER = HexColor("#d0d0d0")
COVER_BG = HexColor("#0b6e4f")
COVER_TEXT = white

# ---- Styles ----
style_cover_label = ParagraphStyle("CoverLabel", fontName="HeadSans-Bold", fontSize=9,
    leading=12, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=2)
style_cover_title = ParagraphStyle("CoverTitle", fontName="HeadSans-Bold", fontSize=40,
    leading=46, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=4)
style_cover_sub = ParagraphStyle("CoverSub", fontName="HeadSans", fontSize=14,
    leading=18, textColor=HexColor("#a5d6a7"), alignment=TA_CENTER, spaceAfter=8)
style_cover_meta_label = ParagraphStyle("CoverMetaLabel", fontName="HeadSans-Bold", fontSize=8,
    leading=10, textColor=HexColor("#a5d6a7"), alignment=TA_CENTER, spaceAfter=1)
style_cover_meta_val = ParagraphStyle("CoverMetaVal", fontName="HeadSans", fontSize=10,
    leading=13, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=1)
style_cover_author = ParagraphStyle("CoverAuthor", fontName="HeadSans", fontSize=10,
    leading=14, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=2)

style_part_label = ParagraphStyle("PartLabel", fontName="HeadSans-Bold", fontSize=9,
    leading=11, textColor=ACCENT, spaceAfter=4, alignment=TA_LEFT)
style_h1 = ParagraphStyle("H1", fontName="HeadSans-Bold", fontSize=22, leading=28,
    textColor=BRAND_DARK, spaceBefore=4, spaceAfter=10, keepWithNext=True)
style_h2 = ParagraphStyle("H2", fontName="HeadSans-Bold", fontSize=14, leading=18,
    textColor=BRAND, spaceBefore=12, spaceAfter=6, keepWithNext=True)
style_h3 = ParagraphStyle("H3", fontName="HeadSans-Bold", fontSize=12, leading=16,
    textColor=TEXT, spaceBefore=8, spaceAfter=4, keepWithNext=True)

style_body = ParagraphStyle("Body", fontName="BodySerif", fontSize=11, leading=16,
    textColor=TEXT, alignment=TA_JUSTIFY, spaceAfter=6)
style_body_muted = ParagraphStyle("BodyMuted", fontName="BodySerif", fontSize=10, leading=14,
    textColor=TEXT_MUTED, alignment=TA_LEFT, spaceAfter=4)
style_code = ParagraphStyle("Code", fontName="LibMono", fontSize=9, leading=12,
    textColor=HexColor("#0b6e4f"), backColor=CODE_BG, borderPadding=6,
    leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=8)
style_bullet = ParagraphStyle("Bullet", fontName="BodySerif", fontSize=11, leading=16,
    textColor=TEXT, leftIndent=20, spaceAfter=3, alignment=TA_JUSTIFY)
style_footer = ParagraphStyle("Footer", fontName="LibMono", fontSize=7, leading=9,
    textColor=TEXT_MUTED, alignment=TA_CENTER)

def escape_xml(text):
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text

def format_inline(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`(.+?)`', r'<font face="LibMono" size="10" color="#0b6e4f">\1</font>', text)
    def replace_link(m):
        t, url = m.group(1), m.group(2)
        if url.startswith("#"):
            return t
        return f'<a href="{url}" color="#0b6e4f">{t}</a>'
    text = re.sub(r'\[(.+?)\]\((.+?)\)', replace_link, text)
    return text

def parse_markdown(md_text):
    blocks = []
    lines = md_text.split("\n")
    i = 0
    in_code = False
    code_lines = []
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                blocks.append(("code", "\n".join(code_lines)))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if line.startswith("### "):
            blocks.append(("h3", line[4:].strip()))
            i += 1; continue
        if line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
            i += 1; continue
        if line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
            i += 1; continue
        if line.strip() == "---":
            blocks.append(("hr", ""))
            i += 1; continue
        if line.startswith("> "):
            q = []
            while i < len(lines) and lines[i].startswith("> "):
                q.append(lines[i][2:]); i += 1
            blocks.append(("quote", "\n".join(q)))
            continue
        if re.match(r"^\s*[-*] ", line):
            b = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                b.append(re.sub(r"^\s*[-*] ", "", lines[i])); i += 1
            blocks.append(("bullets", b))
            continue
        if re.match(r"^\s*\d+\. ", line):
            n = []
            while i < len(lines) and re.match(r"^\s*\d+\. ", lines[i]):
                n.append(re.sub(r"^\s*\d+\. ", "", lines[i])); i += 1
            blocks.append(("numbered", n))
            continue
        if line.strip() == "":
            i += 1; continue
        p = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") \
              and not lines[i].startswith("```") and not re.match(r"^\s*[-*] ", lines[i]) \
              and not re.match(r"^\s*\d+\. ", lines[i]) and not lines[i].startswith("> ") \
              and lines[i].strip() != "---":
            p.append(lines[i]); i += 1
        if p:
            blocks.append(("paragraph", " ".join(p)))
    return blocks

def build_pdf(md_path, pdf_path, is_arabic=False):
    md_text = Path(md_path).read_text()
    lines = md_text.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("## "):
            start_idx = i; break
    md_body = "\n".join(lines[start_idx:])
    blocks = parse_markdown(md_body)
    story = []

    # ---- Cover page ----
    story.append(Spacer(1, 3 * cm))
    icon_path = str(Path(md_path).parent.parent / "download" / "icon-512.png")
    if Path(icon_path).exists():
        story.append(RLImage(icon_path, width=3*cm, height=3*cm, hAlign="CENTER"))
        story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("COMPREHENSIVE USER GUIDE", style_cover_label))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("CorpusMind", style_cover_title))
    story.append(Paragraph("Local-first, AI-native research environment<br/>for corpus linguistics and multimodal discourse analysis", style_cover_sub))
    story.append(Spacer(1, 1 * cm))

    # Metadata badges (like rdat)
    meta_data = [
        ["ENGINE", "PLATFORMS", "LICENSE"],
        ["Python + FastAPI + spaCy", "Win / Mac / Linux / PWA", "AGPL-3.0"],
    ]
    meta_table = Table(meta_data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "HeadSans-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#a5d6a7")),
        ("FONTNAME", (0, 1), (-1, 1), "HeadSans"),
        ("FONTSIZE", (0, 1), (-1, 1), 9),
        ("TEXTCOLOR", (0, 1), (-1, 1), COVER_TEXT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 1 * cm))

    story.append(Paragraph("v0.1.0", style_cover_label))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Dr. Waleed Mandour", style_cover_author))
    story.append(Paragraph("Sultan Qaboos University | ORCID: 0000-0002-9262-5993", style_cover_author))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Prof. Wessam Ibrahim", style_cover_author))
    story.append(Paragraph("ORCID: 0000-0003-0710-6038", style_cover_author))
    story.append(PageBreak())

    # ---- Content ----
    part_num = 0
    for btype, content in blocks:
        if btype == "h2":
            part_num += 1
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(f"PART {part_num}", style_part_label))
            story.append(Paragraph(format_inline(escape_xml(content)), style_h1))
            story.append(HRFlowable(width="100%", thickness=1, color=BRAND_LIGHT, spaceAfter=8))
        elif btype == "h3":
            story.append(Paragraph(format_inline(escape_xml(content)), style_h2))
        elif btype == "paragraph":
            story.append(Paragraph(format_inline(escape_xml(content)), style_body))
        elif btype == "bullets":
            items = [ListItem(Paragraph(format_inline(escape_xml(line)), style_bullet),
                     value="bullet", bulletColor=BRAND) for line in content]
            story.append(ListFlowable(items, bulletType="bullet", bulletColor=BRAND,
                       bulletFontSize=8, leftIndent=16, spaceAfter=6))
        elif btype == "numbered":
            for idx, line in enumerate(content, 1):
                story.append(Paragraph(f"{idx}. {format_inline(escape_xml(line))}",
                    ParagraphStyle("NumItem", parent=style_body, leftIndent=20, spaceAfter=3)))
            story.append(Spacer(1, 4))
        elif btype == "code":
            story.append(Paragraph(escape_xml(content), style_code))
        elif btype == "quote":
            qs = ParagraphStyle("Quote", parent=style_body, fontName="BodySerif-Italic",
                fontSize=10, leading=14, textColor=TEXT_MUTED, leftIndent=16,
                borderColor=BRAND, borderWidth=0, borderPadding=6, spaceAfter=8)
            story.append(Paragraph(format_inline(escape_xml(content)), qs))
        elif btype == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=8))

    # ---- Build document ----
    def page_decorations(canvas, doc):
        canvas.saveState()
        page_num = canvas.getPageNumber()
        if page_num > 1:
            # Footer
            canvas.setFont("LibMono", 7)
            canvas.setFillColor(TEXT_MUTED)
            canvas.drawCentredString(A4[0] / 2, 1.2 * cm,
                f"CORPUSMIND / v0.1.0 / USER GUIDE / PAGE {page_num - 1}")
            # Top accent line
            canvas.setStrokeColor(BRAND)
            canvas.setLineWidth(1)
            canvas.line(2.5 * cm, A4[1] - 1.5 * cm, A4[0] - 2.5 * cm, A4[1] - 1.5 * cm)
        else:
            # Cover page: green background
            canvas.setFillColor(COVER_BG)
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
            # Re-draw content on top (ReportLab draws content first, then canvas)
            # Actually we need to draw the bg before content. Use a different approach:
            # Draw a semi-transparent overlay
            canvas.setFillColor(COVER_BG)
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    def cover_page_bg(canvas, doc):
        """Draw green background ONLY on page 1, before content."""
        canvas.saveState()
        if canvas.getPageNumber() == 1:
            canvas.setFillColor(COVER_BG)
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    def later_pages_footer(canvas, doc):
        """Draw footer on pages after 1."""
        canvas.saveState()
        if canvas.getPageNumber() > 1:
            canvas.setFont("LibMono", 7)
            canvas.setFillColor(TEXT_MUTED)
            canvas.drawCentredString(A4[0] / 2, 1.2 * cm,
                f"CORPUSMIND / v0.1.0 / USER GUIDE / PAGE {canvas.getPageNumber() - 1}")
            canvas.setStrokeColor(BRAND)
            canvas.setLineWidth(1)
            canvas.line(2.5 * cm, A4[1] - 1.5 * cm, A4[0] - 2.5 * cm, A4[1] - 1.5 * cm)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title="CorpusMind User Guide v0.1.0",
        author="Dr. Waleed Mandour and Prof. Wessam Ibrahim",
        subject="User Guide for CorpusMind v0.1.0",
        creator="CorpusMind",
    )

    doc.build(story, onFirstPage=cover_page_bg, onLaterPages=later_pages_footer)
    return pdf_path

if __name__ == "__main__":
    md_path = "/home/z/my-project/corpusmind/docs/USER_GUIDE.md"
    pdf_path = "/home/z/my-project/corpusmind/download/CorpusMind_User_Guide_v0.1.0.pdf"
    build_pdf(md_path, pdf_path)
    print(f"PDF generated: {pdf_path}")
    import os
    print(f"Size: {os.path.getsize(pdf_path) / 1024:.1f} KB")

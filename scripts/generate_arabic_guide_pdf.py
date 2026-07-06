"""Generate the CorpusMind Arabic User Guide PDF with blue theme and Amiri font."""
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether,
    Table, TableStyle, ListFlowable, ListItem, HRFlowable, Image as RLImage
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
import arabic_reshaper
from bidi.algorithm import get_display

# ---- Font registration ----
AMIRI_DIR = "/tmp/amiri_font/Amiri-1.000"
FONT_DIR = "/usr/share/fonts/truetype"

# Arabic font (Amiri - genuine Arabic Naskh font)
pdfmetrics.registerFont(TTFont("Amiri", f"{AMIRI_DIR}/Amiri-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Amiri-Bold", f"{AMIRI_DIR}/Amiri-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Amiri-Italic", f"{AMIRI_DIR}/Amiri-Italic.ttf"))
registerFontFamily("Amiri", normal="Amiri", bold="Amiri-Bold", italic="Amiri-Italic")

# Latin fonts for mixed content
pdfmetrics.registerFont(TTFont("LatinSans", f"{FONT_DIR}/liberation/LiberationSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("LatinSans-Bold", f"{FONT_DIR}/liberation/LiberationSans-Bold.ttf"))
registerFontFamily("LatinSans", normal="LatinSans", bold="LatinSans-Bold")

pdfmetrics.registerFont(TTFont("LibMono", f"{FONT_DIR}/liberation/LiberationMono-Regular.ttf"))

# ---- Blue theme colors ----
BRAND = HexColor("#1565c0")        # Blue 800
BRAND_DARK = HexColor("#0d47a1")   # Blue 900
BRAND_LIGHT = HexColor("#e3f2fd")  # Blue 50
ACCENT = HexColor("#ffb300")       # Amber
TEXT = HexColor("#1a1a2e")
TEXT_MUTED = HexColor("#555555")
CODE_BG = HexColor("#eef0ee")
BORDER = HexColor("#d0d0d0")
COVER_BG = HexColor("#1565c0")
COVER_TEXT = white

# ---- Helper: reshape Arabic text for ReportLab ----
def shape_arabic(text):
    """Reshape Arabic text and apply BiDi for correct rendering in ReportLab."""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def escape_xml(text):
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text

def format_inline(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`(.+?)`', r'<font face="LibMono" size="9" color="#1565c0">\1</font>', text)
    def replace_link(m):
        t, url = m.group(1), m.group(2)
        if url.startswith("#"):
            return t
        return f'<a href="{url}" color="#1565c0">{t}</a>'
    text = re.sub(r'\[(.+?)\]\((.+?)\)', replace_link, text)
    return text

# ---- Styles (Arabic, RTL) ----
style_cover_label = ParagraphStyle("CoverLabel", fontName="LatinSans-Bold", fontSize=9,
    leading=12, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=2)
style_cover_title = ParagraphStyle("CoverTitle", fontName="LatinSans-Bold", fontSize=40,
    leading=46, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=4)
style_cover_sub = ParagraphStyle("CoverSub", fontName="Amiri", fontSize=16,
    leading=22, textColor=HexColor("#bbdefb"), alignment=TA_CENTER, spaceAfter=8)
style_cover_author = ParagraphStyle("CoverAuthor", fontName="Amiri", fontSize=11,
    leading=16, textColor=COVER_TEXT, alignment=TA_CENTER, spaceAfter=2)

style_part_label = ParagraphStyle("PartLabel", fontName="LatinSans-Bold", fontSize=9,
    leading=11, textColor=ACCENT, spaceAfter=4, alignment=TA_RIGHT)
style_h1 = ParagraphStyle("H1", fontName="Amiri-Bold", fontSize=20, leading=28,
    textColor=BRAND_DARK, spaceBefore=4, spaceAfter=10, alignment=TA_RIGHT, keepWithNext=True)
style_h2 = ParagraphStyle("H2", fontName="Amiri-Bold", fontSize=14, leading=20,
    textColor=BRAND, spaceBefore=12, spaceAfter=6, alignment=TA_RIGHT, keepWithNext=True)
style_h3 = ParagraphStyle("H3", fontName="Amiri-Bold", fontSize=12, leading=18,
    textColor=TEXT, spaceBefore=8, spaceAfter=4, alignment=TA_RIGHT, keepWithNext=True)

style_body = ParagraphStyle("Body", fontName="Amiri", fontSize=12, leading=20,
    textColor=TEXT, alignment=TA_RIGHT, spaceAfter=6)
style_code = ParagraphStyle("Code", fontName="LibMono", fontSize=9, leading=12,
    textColor=HexColor("#1565c0"), backColor=CODE_BG, borderPadding=6,
    leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=8, alignment=TA_LEFT)
style_bullet = ParagraphStyle("Bullet", fontName="Amiri", fontSize=12, leading=20,
    textColor=TEXT, rightIndent=20, spaceAfter=3, alignment=TA_RIGHT)
style_footer = ParagraphStyle("Footer", fontName="LibMono", fontSize=7, leading=9,
    textColor=TEXT_MUTED, alignment=TA_CENTER)


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


def build_arabic_pdf(md_path, pdf_path):
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
    story.append(Paragraph(shape_arabic("دليل المستخدم الشامل"), style_cover_sub))
    story.append(Spacer(1, 1 * cm))

    # Metadata badges
    meta_data = [
        ["ENGINE", "PLATFORMS", "LICENSE"],
        ["Python + FastAPI + spaCy", "Win / Mac / Linux / PWA", "AGPL-3.0"],
    ]
    meta_table = Table(meta_data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "LatinSans-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#bbdefb")),
        ("FONTNAME", (0, 1), (-1, 1), "LatinSans"),
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
    story.append(Paragraph(shape_arabic("د. وليد مندور"), style_cover_author))
    story.append(Paragraph("Sultan Qaboos University | ORCID: 0000-0002-9262-5993", style_cover_author))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(shape_arabic("أ.د. وسام إبراهيم"), style_cover_author))
    story.append(Paragraph("ORCID: 0000-0003-0710-6038", style_cover_author))
    story.append(PageBreak())

    # ---- Content ----
    part_num = 0
    for btype, content in blocks:
        if btype == "h2":
            part_num += 1
            story.append(Spacer(1, 0.3 * cm))
            story.append(Paragraph(f"PART {part_num}", style_part_label))
            story.append(Paragraph(shape_arabic(format_inline(escape_xml(content))), style_h1))
            story.append(HRFlowable(width="100%", thickness=1, color=BRAND_LIGHT, spaceAfter=8))
        elif btype == "h3":
            story.append(Paragraph(shape_arabic(format_inline(escape_xml(content))), style_h2))
        elif btype == "paragraph":
            story.append(Paragraph(shape_arabic(format_inline(escape_xml(content))), style_body))
        elif btype == "bullets":
            items = [ListItem(Paragraph(shape_arabic(format_inline(escape_xml(line))), style_bullet),
                     value="bullet", bulletColor=BRAND) for line in content]
            story.append(ListFlowable(items, bulletType="bullet", bulletColor=BRAND,
                       bulletFontSize=8, rightIndent=16, spaceAfter=6))
        elif btype == "numbered":
            for idx, line in enumerate(content, 1):
                story.append(Paragraph(f"{idx}. {shape_arabic(format_inline(escape_xml(line)))}",
                    ParagraphStyle("NumItem", parent=style_body, rightIndent=20, spaceAfter=3)))
            story.append(Spacer(1, 4))
        elif btype == "code":
            story.append(Paragraph(escape_xml(content), style_code))
        elif btype == "quote":
            qs = ParagraphStyle("Quote", parent=style_body, fontName="Amiri-Italic",
                fontSize=11, leading=18, textColor=TEXT_MUTED, rightIndent=16,
                borderColor=BRAND, borderWidth=0, borderPadding=6, spaceAfter=8)
            story.append(Paragraph(shape_arabic(format_inline(escape_xml(content))), qs))
        elif btype == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=8))

    # ---- Build document ----
    def cover_page_bg(canvas, doc):
        canvas.saveState()
        if canvas.getPageNumber() == 1:
            canvas.setFillColor(COVER_BG)
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    def later_pages_footer(canvas, doc):
        canvas.saveState()
        if canvas.getPageNumber() > 1:
            canvas.setFont("LibMono", 7)
            canvas.setFillColor(TEXT_MUTED)
            canvas.drawCentredString(A4[0] / 2, 1.2 * cm,
                f"CORPUSMIND / v0.1.0 / DALLL AL-MUSTAKHDEM / SAFHA {canvas.getPageNumber() - 1}")
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
        title="CorpusMind Arabic User Guide v0.1.0",
        author="Dr. Waleed Mandour and Prof. Wessam Ibrahim",
        subject="Arabic User Guide for CorpusMind v0.1.0",
        creator="CorpusMind",
    )

    doc.build(story, onFirstPage=cover_page_bg, onLaterPages=later_pages_footer)
    return pdf_path


if __name__ == "__main__":
    md_path = "/home/z/my-project/corpusmind/docs/USER_GUIDE_AR.md"
    pdf_path = "/home/z/my-project/corpusmind/download/CorpusMind_User_Guide_Arabic_v0.1.0.pdf"
    build_arabic_pdf(md_path, pdf_path)
    import os
    print(f"Arabic PDF generated: {pdf_path}")
    print(f"Size: {os.path.getsize(pdf_path) / 1024:.1f} KB")

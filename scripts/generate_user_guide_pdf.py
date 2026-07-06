"""Generate the CorpusMind User Guide PDF using ReportLab."""
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER
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

# ---- Colors ----
BRAND = HexColor("#0b6e4f")
BRAND_DARK = HexColor("#095c41")
ACCENT = HexColor("#e8b339")
TEXT = HexColor("#1c1f1d")
TEXT_MUTED = HexColor("#5a5f5c")
BG_SUBTLE = HexColor("#f5f6f5")
CODE_BG = HexColor("#eef0ee")
BORDER = HexColor("#d8dad8")

# ---- Styles ----
styles = getSampleStyleSheet()

style_cover_title = ParagraphStyle("CoverTitle", fontName="HeadSans-Bold", fontSize=36, leading=42,
    textColor=BRAND_DARK, alignment=TA_CENTER, spaceAfter=8)
style_cover_sub = ParagraphStyle("CoverSub", fontName="HeadSans", fontSize=14, leading=20,
    textColor=TEXT_MUTED, alignment=TA_CENTER, spaceAfter=4)
style_cover_meta = ParagraphStyle("CoverMeta", fontName="LibMono", fontSize=10, leading=14,
    textColor=TEXT_MUTED, alignment=TA_CENTER)

style_h1 = ParagraphStyle("H1", fontName="HeadSans-Bold", fontSize=18, leading=24,
    textColor=BRAND, spaceBefore=20, spaceAfter=8, keepWithNext=True)
style_h2 = ParagraphStyle("H2", fontName="HeadSans-Bold", fontSize=14, leading=18,
    textColor=BRAND_DARK, spaceBefore=14, spaceAfter=6, keepWithNext=True)
style_h3 = ParagraphStyle("H3", fontName="HeadSans-Bold", fontSize=12, leading=16,
    textColor=TEXT, spaceBefore=10, spaceAfter=4, keepWithNext=True)

style_body = ParagraphStyle("Body", fontName="BodySerif", fontSize=11, leading=16,
    textColor=TEXT, alignment=TA_LEFT, spaceAfter=6)
style_body_muted = ParagraphStyle("BodyMuted", fontName="BodySerif", fontSize=10, leading=14,
    textColor=TEXT_MUTED, alignment=TA_LEFT, spaceAfter=4)
style_code = ParagraphStyle("Code", fontName="LibMono", fontSize=9, leading=12,
    textColor=HexColor("#2e7d32"), backColor=CODE_BG, borderPadding=6,
    leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=8)
style_code_inline = ParagraphStyle("CodeInline", fontName="LibMono", fontSize=10, leading=14,
    textColor=BRAND)
style_toc = ParagraphStyle("TOC", fontName="BodySerif", fontSize=11, leading=16,
    textColor=TEXT, leftIndent=12, spaceAfter=2)
style_toc_h = ParagraphStyle("TOCh", fontName="HeadSans-Bold", fontSize=16, leading=22,
    textColor=BRAND, spaceAfter=10)
style_bullet = ParagraphStyle("Bullet", fontName="BodySerif", fontSize=11, leading=16,
    textColor=TEXT, leftIndent=20, spaceAfter=3)
style_numbered = ParagraphStyle("Numbered", fontName="BodySerif", fontSize=11, leading=16,
    textColor=TEXT, leftIndent=24, spaceAfter=3)
style_footer = ParagraphStyle("Footer", fontName="LibMono", fontSize=8, leading=10,
    textColor=TEXT_MUTED, alignment=TA_CENTER)

def escape_xml(text):
    """Escape XML special characters for ReportLab Paragraph."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text

def format_inline(text):
    """Convert markdown inline formatting to ReportLab tags."""
    # Bold **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Inline code `text`
    text = re.sub(r'`(.+?)`', r'<font face="LibMono" size="10" color="#0b6e4f">\1</font>', text)
    # Links [text](url) - only external links, strip internal anchors
    def replace_link(m):
        text = m.group(1)
        url = m.group(2)
        if url.startswith("#"):
            return text  # Internal anchor - just show the text
        return f'<a href="{url}" color="#0b6e4f">{text}</a>'
    text = re.sub(r'\[(.+?)\]\((.+?)\)', replace_link, text)
    return text

def parse_markdown(md_text):
    """Parse markdown into a list of (type, content) tuples."""
    blocks = []
    lines = md_text.split("\n")
    i = 0
    in_code_block = False
    code_lines = []

    while i < len(lines):
        line = lines[i]

        # Code block start/end
        if line.strip().startswith("```"):
            if in_code_block:
                blocks.append(("code", "\n".join(code_lines)))
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # Headings
        if line.startswith("### "):
            blocks.append(("h3", line[4:].strip()))
            i += 1
            continue
        if line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
            i += 1
            continue
        if line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
            i += 1
            continue

        # Horizontal rule
        if line.strip() == "---":
            blocks.append(("hr", ""))
            i += 1
            continue

        # Blockquote
        if line.startswith("> "):
            quote_lines = []
            while i < len(lines) and lines[i].startswith("> "):
                quote_lines.append(lines[i][2:])
                i += 1
            blocks.append(("quote", "\n".join(quote_lines)))
            continue

        # Bullet list
        if re.match(r"^\s*[-*] ", line):
            bullet_lines = []
            while i < len(lines) and re.match(r"^\s*[-*] ", lines[i]):
                bullet_lines.append(re.sub(r"^\s*[-*] ", "", lines[i]))
                i += 1
            blocks.append(("bullets", bullet_lines))
            continue

        # Numbered list
        if re.match(r"^\s*\d+\. ", line):
            num_lines = []
            while i < len(lines) and re.match(r"^\s*\d+\. ", lines[i]):
                num_lines.append(re.sub(r"^\s*\d+\. ", "", lines[i]))
                i += 1
            blocks.append(("numbered", num_lines))
            continue

        # Empty line
        if line.strip() == "":
            i += 1
            continue

        # Regular paragraph (collect consecutive non-empty lines)
        para_lines = []
        while i < len(lines) and lines[i].strip() != "" and not lines[i].startswith("#") \
              and not lines[i].startswith("```") and not re.match(r"^\s*[-*] ", lines[i]) \
              and not re.match(r"^\s*\d+\. ", lines[i]) and not lines[i].startswith("> ") \
              and lines[i].strip() != "---":
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            blocks.append(("paragraph", " ".join(para_lines)))

    return blocks


def build_pdf(md_path, pdf_path):
    """Build the PDF from markdown."""
    md_text = Path(md_path).read_text()

    # Skip the top-level title and blockquote (we'll make a proper cover)
    # Find the first ## heading
    lines = md_text.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("## "):
            start_idx = i
            break
    # Also include the table of contents section
    md_body = "\n".join(lines[start_idx:])

    blocks = parse_markdown(md_body)

    # Build the story
    story = []

    # ---- Cover page ----
    story.append(Spacer(1, 3 * cm))
    
    # App icon
    icon_path = str(Path(md_path).parent.parent / "download" / "icon-512.png")
    if Path(icon_path).exists():
        story.append(RLImage(icon_path, width=3*cm, height=3*cm, hAlign="CENTER"))
        story.append(Spacer(1, 0.5 * cm))
    
    story.append(Paragraph("CorpusMind", style_cover_title))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("User Guide", ParagraphStyle("CoverSub2", fontName="HeadSans", fontSize=20,
        leading=26, textColor=BRAND, alignment=TA_CENTER, spaceAfter=8)))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("Version 0.7.0 | Pre-Release | AGPL-3.0-only", style_cover_meta))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Local-first, AI-native research environment for<br/>corpus linguistics and multimodal discourse analysis", style_cover_meta))
    story.append(Spacer(1, 1.5 * cm))
    story.append(HRFlowable(width="60%", thickness=2, color=BRAND, spaceBefore=10, spaceAfter=10, hAlign="CENTER"))
    story.append(Spacer(1, 0.5 * cm))
    
    # Authors and citation on cover
    author_style = ParagraphStyle("CoverAuthor", fontName="HeadSans", fontSize=10, leading=14,
        textColor=TEXT_MUTED, alignment=TA_CENTER, spaceAfter=2)
    story.append(Paragraph("Dr. Waleed Mandour (Sultan Qaboos University, ORCID: 0000-0002-9262-5993)", author_style))
    story.append(Paragraph("Prof. Wessam Ibrahim", author_style))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("97 tests | 25 AI tools | 85 API routes | 12 frameworks | 20 formulas", style_cover_meta))
    story.append(PageBreak())

    # ---- Table of contents ----
    story.append(Paragraph("Table of Contents", style_toc_h))
    story.append(Spacer(1, 0.5 * cm))

    toc_entries = []
    for btype, content in blocks:
        if btype == "h2":
            # Check if it starts with a number (like "1. Installation")
            match = re.match(r"^(\d+)\.\s+(.+)", content)
            if match:
                num = match.group(1)
                title = match.group(2)
                toc_entries.append(f"{num}. {title}")
            else:
                toc_entries.append(content)

    for entry in toc_entries:
        story.append(Paragraph(entry, style_toc))

    story.append(PageBreak())

    # ---- Body content ----
    for btype, content in blocks:
        if btype == "h2":
            story.append(Paragraph(format_inline(escape_xml(content)), style_h1))
        elif btype == "h3":
            story.append(Paragraph(format_inline(escape_xml(content)), style_h2))
        elif btype == "paragraph":
            story.append(Paragraph(format_inline(escape_xml(content)), style_body))
        elif btype == "bullets":
            items = [ListItem(Paragraph(format_inline(escape_xml(line)), style_bullet), value="bullet",
                     bulletColor=BRAND) for line in content]
            story.append(ListFlowable(items, bulletType="bullet", bulletColor=BRAND,
                       bulletFontSize=8, leftIndent=16, spaceAfter=6))
        elif btype == "numbered":
            items = [Paragraph(format_inline(escape_xml(line)), style_numbered) for line in content]
            for idx, item in enumerate(items, 1):
                story.append(Paragraph(f"{idx}. {item.text}", style_numbered))
            story.append(Spacer(1, 4))
        elif btype == "code":
            # Escape and render as monospace block
            escaped = escape_xml(content)
            story.append(Paragraph(escaped, style_code))
        elif btype == "quote":
            escaped = format_inline(escape_xml(content))
            quote_style = ParagraphStyle("Quote", parent=style_body, fontName="BodySerif-Italic",
                fontSize=10, leading=14, textColor=TEXT_MUTED, leftIndent=16, rightIndent=16,
                borderColor=BRAND, borderWidth=0, borderPadding=6, spaceAfter=8)
            story.append(Paragraph(escaped, quote_style))
        elif btype == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=8))

    # ---- Build the document ----
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("LibMono", 8)
        canvas.setFillColor(TEXT_MUTED)
        page_num = canvas.getPageNumber()
        if page_num > 2:  # Skip cover and TOC
            canvas.drawCentredString(A4[0] / 2, 1.5 * cm, f"CorpusMind User Guide v0.7.0 | Page {page_num - 2}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title="CorpusMind User Guide v0.7.0",
        author="CorpusMind Contributors",
        subject="User Guide for CorpusMind v0.7.0 Pre-Release",
        creator="CorpusMind",
    )

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return pdf_path


if __name__ == "__main__":
    md_path = "/home/z/my-project/corpusmind/docs/USER_GUIDE.md"
    pdf_path = "/home/z/my-project/corpusmind/download/CorpusMind_User_Guide_v0.7.0.pdf"
    build_pdf(md_path, pdf_path)
    print(f"PDF generated: {pdf_path}")
    import os
    size = os.path.getsize(pdf_path)
    print(f"Size: {size / 1024:.1f} KB")

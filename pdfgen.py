"""توليد ملفات PDF من نص (يدعم العربية + Markdown بسيط)."""
import html
import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)

import config

_fonts_registered = False


def _register_fonts() -> str:
    global _fonts_registered
    regular = config.FONTS_DIR / "Amiri-Regular.ttf"
    bold = config.FONTS_DIR / "Amiri-Bold.ttf"
    if regular.exists():
        if not _fonts_registered:
            pdfmetrics.registerFont(TTFont("Amiri", str(regular)))
            if bold.exists():
                pdfmetrics.registerFont(TTFont("Amiri-Bold", str(bold)))
                pdfmetrics.registerFontFamily(
                    "Amiri",
                    normal="Amiri",
                    bold="Amiri-Bold",
                    italic="Amiri",
                    boldItalic="Amiri-Bold",
                )
            _fonts_registered = True
        return "Amiri"
    return "Helvetica"


def _ar(text: str) -> str:
    """يعيد تشكيل النص العربي وترتيبه بصريًا ليعمل داخل PDF."""
    return get_display(arabic_reshaper.reshape(text))


def _inline(text: str) -> str:
    """يحوّل **عريض** ويهرب وسوم HTML ثم يعيد تشكيل العربية."""
    parts = re.split(r"(\*\*.+?\*\*)", text)
    out = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append("<b>" + _ar(html.escape(part[2:-2])) + "</b>")
        else:
            out.append(_ar(html.escape(part)))
    return "".join(out)


def generate_pdf(text: str, out_path: Path, title: str = "مستند") -> Path:
    font = _register_fonts()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
    )

    body = ParagraphStyle(
        "Body", fontName=font, fontSize=13, leading=22,
        alignment=TA_RIGHT, spaceAfter=6, splitLongWords=1,
    )
    h1 = ParagraphStyle(
        "H1", parent=body, fontSize=20, leading=28, spaceBefore=14, spaceAfter=8
    )
    h2 = ParagraphStyle(
        "H2", parent=body, fontSize=16, leading=24, spaceBefore=12, spaceAfter=6
    )
    h3 = ParagraphStyle(
        "H3", parent=body, fontSize=14, leading=22, spaceBefore=10, spaceAfter=4
    )
    code_style = ParagraphStyle(
        "Code", fontName="Courier", fontSize=10, leading=14,
        alignment=TA_LEFT, backColor="#f2f2f2", borderPadding=6,
    )

    story = []
    lines = text.splitlines()
    in_code = False
    code_buffer = []

    def flush_code():
        if code_buffer:
            story.append(Preformatted("\n".join(code_buffer), code_style))
            story.append(Spacer(1, 6))
            code_buffer.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buffer.append(line)
            continue
        if not stripped:
            story.append(Spacer(1, 6))
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(_inline(stripped[4:]), h3))
        elif stripped.startswith("## "):
            story.append(Paragraph(_inline(stripped[3:]), h2))
        elif stripped.startswith("# "):
            story.append(Paragraph(_inline(stripped[2:]), h1))
        elif stripped.startswith(("- ", "• ")):
            story.append(Paragraph("•  " + _inline(stripped[2:]), body))
        elif re.match(r"^\d+[.)]\s", stripped):
            story.append(Paragraph(_inline(stripped), body))
        elif stripped.startswith("> "):
            story.append(Paragraph(_inline(stripped[2:]), body))
        elif stripped in ("---", "***", "___"):
            story.append(HRFlowable(width="100%", thickness=1))
        else:
            story.append(Paragraph(_inline(stripped), body))

    if in_code:
        flush_code()

    doc.build(story)
    return out_path

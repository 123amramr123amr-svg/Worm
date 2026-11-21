"""حفظ الملفات المرفوعة واستخراج النص منها (PDF, DOCX, XLSX, نصية...)."""
import re
import unicodedata
from pathlib import Path

import config

TEXT_EXTS = {
    ".txt", ".md", ".py", ".html", ".htm", ".json", ".csv", ".js", ".ts",
    ".css", ".xml", ".yaml", ".yml", ".log", ".ini", ".sh", ".sql",
    ".java", ".c", ".cpp", ".h", ".go", ".php", ".rb", ".swift", ".kt",
    ".rs", ".env", ".cfg", ".toml", ".bat", ".ps1",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def output_path(user_id: int, filename: str) -> Path:
    directory = config.OUTPUT_DIR / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


def write_output(user_id: int, filename: str, text: str) -> Path:
    path = output_path(user_id, filename)
    path.write_text(text, encoding="utf-8")
    return path


def write_output_bytes(user_id: int, filename: str, data: bytes) -> Path:
    path = output_path(user_id, filename)
    path.write_bytes(data)
    return path


async def save_upload(user_id: int, filename: str, tg_file) -> Path:
    """ينزّل ملفًا من تيليجرام ويحفظه في مجلد الرفع الخاص بالمستخدم."""
    safe = re.sub(r"[^\w.\-() ]+", "_", filename or "file").strip() or "file"
    directory = config.UPLOAD_DIR / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe
    data = await tg_file.download_as_bytearray()
    path.write_bytes(bytes(data))
    return path


def extract_text(path: Path):
    """يستخرج النص من ملف. يرجع None إذا كان النوع غير مدعوم."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf_text(path)
        if ext in TEXT_EXTS:
            return path.read_text(encoding="utf-8", errors="replace")
        if ext == ".docx":
            return _docx_text(path)
        if ext == ".xlsx":
            return _xlsx_text(path)
    except Exception:
        return None
    return None


def _normalize_arabic(text: str) -> str:
    """يرجّع الحروف العربية من صيغة presentation forms إلى صيغتها الأصلية.

    ملفات PDF المولّدة تحتوي الحروف مشكّلة بصيغة presentation forms
    (ﻋﻨﻮﺍﻥ) وهي غير قابلة للقراءة كنص عادي، فنطبّعها باستخدام NFKC.
    """
    if not text:
        return text
    # NFKC يحوّل presentation forms إلى حروفها الأساسية
    text = unicodedata.normalize("NFKC", text)
    # إزالة التشكيل (harakat) إن وُجدت للحفاظ على وضوح النص
    text = "".join(
        ch for ch in text
        if not (unicodedata.combining(ch) or "ً" <= ch <= "ْ")
    )
    return text


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        raw = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        import fitz  # PyMuPDF كبديل

        document = fitz.open(str(path))
        raw = "\n".join(page.get_text() for page in document)
    return _normalize_arabic(raw)


def _docx_text(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _xlsx_text(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for sheet in workbook.worksheets:
        lines.append(f"== ورقة: {sheet.title} ==")
        for row in sheet.iter_rows(values_only=True):
            values = [str(v) for v in row if v is not None]
            if values:
                lines.append(" | ".join(values))
    return "\n".join(lines)

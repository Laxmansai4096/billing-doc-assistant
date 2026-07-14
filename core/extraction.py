"""
Extraction layer.

Converts an uploaded PDF or DOCX file into a list of `PageBlock` objects
that downstream code (LLM extraction, ledger, viewer) can cite by label.

Design notes
------------
* PDF: we use `pdfplumber` (not just raw text extraction) because billing
  documents almost always contain their line items in *tables*. Each
  page's extracted tables are appended below the free text so the LLM
  sees both narrative and tabular content for that page, and page
  numbers are always exact.

* DOCX: Word has no fixed pagination in the file format itself -- pages
  are a rendering-time concept. We do our best in this order:
    1. If the document contains explicit page breaks (`<w:br w:type="page"/>`),
       we honor them and produce real "Page N" labels.
    2. Otherwise we fall back to Heading-1/Heading-2 boundaries and label
       blocks "Section: <heading text>".
    3. If neither is present, we fall back to fixed-size "Part N" chunks.
  Paragraphs and tables are walked in true document order so billing
  tables end up attached to the correct section/page.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
import re
import os
import shutil
import subprocess
import tempfile

import pdfplumber
import docx
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from core.models import PageBlock


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def _table_to_text(table_rows: List[List[str]]) -> str:
    if not table_rows or not any(table_rows):
        return ""
    
    # Clean rows and cells
    cleaned_rows = []
    for row in table_rows:
        cleaned_rows.append([(c or "").strip().replace("\n", " ") for c in row])
        
    # Find max number of columns
    max_cols = max(len(r) for r in cleaned_rows)
    if max_cols == 0:
        return ""
        
    # Normalize row lengths
    for r in cleaned_rows:
        while len(r) < max_cols:
            r.append("")
            
    # Convert to markdown table format
    lines = ["[TABLE]"]
    
    # First row is header
    header = cleaned_rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    
    # Remaining rows
    for row in cleaned_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
        
    lines.append("[/TABLE]")
    return "\n".join(lines)


def extract_pdf_pages(path: str) -> Tuple[List[PageBlock], bool]:
    """Returns (pages, has_extractable_text)."""
    pages: List[PageBlock] = []
    any_text = False

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            # 1. Find all tables on the page
            tables = []
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
                
            # Sort tables from top to bottom
            tables = sorted(tables, key=lambda t: t.bbox[1])
            
            parts = []
            last_bottom = 0
            
            # 2. Extract visual elements sequentially
            for t in tables:
                x0, top, x1, bottom = t.bbox
                
                # Extract text above this table (since the last table's bottom)
                if top > last_bottom:
                    box = (0, max(0, last_bottom), page.width, min(page.height, top))
                    if box[3] > box[1]:
                        try:
                            cropped = page.crop(box, relative=False)
                            text_segment = cropped.extract_text()
                            if text_segment and text_segment.strip():
                                parts.append(text_segment.strip())
                                any_text = True
                        except Exception:
                            pass
                
                # Extract the table content and convert to clean markdown table
                try:
                    table_data = t.extract()
                    if table_data:
                        md_table = _table_to_text(table_data)
                        if md_table:
                            parts.append(md_table)
                            any_text = True
                except Exception:
                    pass
                    
                last_bottom = bottom
                
            # 3. Extract remaining text below the last table
            if last_bottom < page.height:
                box = (0, max(0, last_bottom), page.width, page.height)
                if box[3] > box[1]:
                    try:
                        cropped = page.crop(box, relative=False)
                        text_segment = cropped.extract_text()
                        if text_segment and text_segment.strip():
                            parts.append(text_segment.strip())
                            any_text = True
                    except Exception:
                        pass
                        
            # Fallback: if slicing failed or returned no text, extract all text as standard
            full_text = "\n\n".join(parts).strip()
            if not full_text:
                try:
                    full_text = page.extract_text() or ""
                    if full_text.strip():
                        any_text = True
                except Exception:
                    full_text = ""

            # Extract basic image metadata and insert placeholders so the LLM
            # knows when a page contains charts/figures. We don't run OCR
            # here for images; we merely note their presence and size.
            images = []
            try:
                for img in getattr(page, "images", []) or []:
                    # pdfplumber image dict contains width/height and bbox
                    w = img.get("width") or (img.get("x1", 0) - img.get("x0", 0))
                    h = img.get("height") or (img.get("y1", 0) - img.get("y0", 0))
                    # Heuristic: treat large, wide images as charts
                    page_w = getattr(page, "width", None)
                    page_h = getattr(page, "height", None)
                    is_chart = False
                    try:
                        if page_w and page_h and w and h:
                            # relative area heuristic
                            rel_area = (w * h) / (page_w * page_h)
                            if rel_area > 0.06 and (w / max(h, 1)) > 1.2:
                                is_chart = True
                    except Exception:
                        is_chart = False
                    images.append({"w": int(w or 0), "h": int(h or 0), "chart": is_chart})
            except Exception:
                images = []

            # Append image placeholders after text/tables so they're visible
            # to downstream extraction and the LLM. Use [CHART] when our
            # heuristic thinks it's a chart-like image.
            image_texts = []
            for im in images:
                if im.get("chart"):
                    image_texts.append(f"[CHART image {im['w']}x{im['h']}]")
                else:
                    image_texts.append(f"[IMAGE {im['w']}x{im['h']}]")
            if image_texts:
                any_text = any_text or False
                full_text = (full_text + "\n\n" + "\n".join(image_texts)).strip()

            pages.append(
                PageBlock(
                    index=i,
                    page_number=i,
                    label=f"Page {i}",
                    text=full_text,
                    is_true_page=True,
                )
            )

    return pages, any_text


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

def _iter_block_items(document):
    """Yield paragraphs and tables in true document order."""
    parent_elm = document.element.body
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield DocxParagraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield DocxTable(child, document)


def _docx_table_to_text(table: DocxTable) -> str:
    rows = []
    for row in table.rows:
        rows.append([cell.text for cell in row.cells])
    return _table_to_text(rows)


def _find_soffice_from_registry() -> Optional[str]:
    try:
        import winreg
    except ImportError:
        return None
    for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe",
            r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe"
        ):
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, "")
                    if path and os.path.exists(path):
                        return path
            except OSError:
                pass
        try:
            with winreg.OpenKey(hkey, r"SOFTWARE\LibreOffice\UNO\InstallPath") as key:
                dir_path, _ = winreg.QueryValueEx(key, "")
                if dir_path:
                    path = os.path.join(dir_path, "soffice.exe")
                    if os.path.exists(path):
                        return path
        except OSError:
            pass
    return None


def convert_to_pdf_bytes(file_bytes: bytes, filename: str):
    """Convert common document formats to PDF bytes when possible."""
    if not file_bytes:
        return None

    lower = filename.lower()
    if lower.endswith(".pdf"):
        return file_bytes

    supported_exts = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf", ".txt"}
    if os.path.splitext(lower)[1] not in supported_exts:
        return None

    with tempfile.TemporaryDirectory(prefix="pdf-convert-", dir=tempfile.gettempdir()) as tmpdir:
        input_name = os.path.basename(filename)
        input_path = os.path.join(tmpdir, input_name)
        with open(input_path, "wb") as fh:
            fh.write(file_bytes)

        output_path = os.path.join(tmpdir, f"{os.path.splitext(input_name)[0]}.pdf")

        docx2pdf_candidates = []
        try:
            from docx2pdf import convert  # type: ignore
            docx2pdf_candidates.append(("docx2pdf", convert))
        except Exception:
            pass

        # For Word files (.docx / .doc), prioritize docx2pdf if available (native MS Word yields perfect layout rendering)
        is_word = lower.endswith((".docx", ".doc"))
        if is_word and docx2pdf_candidates:
            for _, convert_fn in docx2pdf_candidates:
                try:
                    convert_fn(input_path, output_path)
                    if os.path.exists(output_path):
                        with open(output_path, "rb") as fh:
                            return fh.read()
                except Exception:
                    pass

        # Build candidate programs for LibreOffice headless conversion
        programs = []
        registry_soffice = _find_soffice_from_registry()
        if registry_soffice:
            programs.append(registry_soffice)
        
        programs.extend([
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "libreoffice",
            "soffice",
            "soffice.exe",
        ])

        for program in programs:
            if not program:
                continue
            try:
                subprocess.run(
                    [program, "--headless", "--convert-to", "pdf", "--outdir", tmpdir, input_path],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=120,
                )
                if os.path.exists(output_path):
                    with open(output_path, "rb") as fh:
                        return fh.read()
            except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
                continue

        # Fallback to docx2pdf if we checked LibreOffice first (e.g. for non-Word formats)
        if not is_word and docx2pdf_candidates:
            for _, convert_fn in docx2pdf_candidates:
                try:
                    convert_fn(input_path, output_path)
                    if os.path.exists(output_path):
                        with open(output_path, "rb") as fh:
                            return fh.read()
                except Exception:
                    pass

    return None


def _paragraph_has_page_break(paragraph: DocxParagraph) -> bool:
    for run in paragraph.runs:
        for br in run._element.findall(qn("w:br")):
            if br.get(qn("w:type")) == "page":
                return True
    return False


def extract_docx_pages(path: str) -> Tuple[List[PageBlock], bool]:
    """Returns (pages, has_extractable_text). Falls back gracefully when
    the document has no explicit page breaks or headings."""
    document = docx.Document(path)
    blocks = list(_iter_block_items(document))

    has_explicit_breaks = any(
        isinstance(b, DocxParagraph) and _paragraph_has_page_break(b) for b in blocks
    )
    has_headings = any(
        isinstance(b, DocxParagraph) and (b.style.name or "").lower().startswith("heading")
        for b in blocks
    )

    pages: List[PageBlock] = []
    current_text: List[str] = []
    current_heading = None
    current_page_num = 1
    any_text = False

    def flush(force_label=None):
        nonlocal current_text
        text = "\n".join(t for t in current_text if t.strip()).strip()
        current_text = []
        if not text:
            return
        nonlocal any_text
        any_text = True
        idx = len(pages) + 1
        if has_explicit_breaks:
            label = f"Page {current_page_num}"
            page_number = current_page_num
            is_true = True
        elif has_headings and current_heading:
            label = f"Section: {current_heading}"
            page_number = None
            is_true = False
        else:
            label = force_label or f"Part {idx}"
            page_number = None
            is_true = False
        pages.append(
            PageBlock(index=idx, page_number=page_number, label=label, text=text, is_true_page=is_true)
        )

    CHARS_PER_FALLBACK_PART = 3500
    running_chars = 0

    for block in blocks:
        if isinstance(block, DocxParagraph):
            style_name = (block.style.name or "").lower()
            is_heading = style_name.startswith("heading")

            if is_heading and not has_explicit_breaks:
                # Start a new section at each heading boundary.
                flush()
                current_heading = block.text.strip() or current_heading

            if block.text.strip():
                current_text.append(block.text)
                running_chars += len(block.text)

            if has_explicit_breaks and _paragraph_has_page_break(block):
                flush()
                current_page_num += 1
                running_chars = 0
            elif not has_explicit_breaks and not has_headings and running_chars >= CHARS_PER_FALLBACK_PART:
                flush()
                running_chars = 0

        elif isinstance(block, DocxTable):
            current_text.append(_docx_table_to_text(block))

    flush()

    if not pages:
        pages.append(PageBlock(index=1, page_number=None, label="Document", text="", is_true_page=False))

    return pages, any_text


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def extract_document(path: str, filename: str) -> Tuple[List[PageBlock], bool, str]:
    """Returns (pages, has_extractable_text, doc_type)."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        pages, has_text = extract_pdf_pages(path)
        return pages, has_text, "pdf"

    try:
        with open(path, "rb") as fh:
            file_bytes = fh.read()
    except OSError:
        file_bytes = b""

    pdf_bytes = convert_to_pdf_bytes(file_bytes, filename)
    if pdf_bytes:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(pdf_bytes)
        try:
            pages, has_text = extract_pdf_pages(tmp_path)
            return pages, has_text, "pdf"
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if lower.endswith((".docx", ".doc")):
        pages, has_text = extract_docx_pages(path)
        return pages, has_text, "docx"

    if lower.endswith((".txt", ".rtf")):
        text = ""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except Exception:
            text = ""
        if text.strip():
            pages = [PageBlock(index=1, page_number=None, label="Document", text=text, is_true_page=False)]
            return pages, True, "docx"

    raise ValueError(f"Unsupported file type: {filename}. Please upload a PDF, Word document, or a text-based file.")

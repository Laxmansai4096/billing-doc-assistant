"""
Helpers for the "Document Viewer" pane: embedding a PDF with a page-jump,
and locating the right text block for DOCX (which has no true pages).
"""

import base64
from typing import List, Optional

from core.models import PageBlock


def pdf_data_uri(pdf_bytes: bytes) -> str:
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    return f"data:application/pdf;base64,{b64}"


def pdf_iframe_html(pdf_bytes: bytes, page: int, height: int = 720) -> str:
    """Returns an <iframe> that opens the PDF at the given page using the
    browser's native PDF viewer (#page=N). Works in Chrome/Edge/Firefox's
    built-in viewer; falls back to page 1 if the browser ignores the anchor."""
    uri = pdf_data_uri(pdf_bytes)
    src = f"{uri}#page={page}&view=FitH"
    return f"""
    <div style="border:1px solid var(--border-color, #333); border-radius:8px; overflow:hidden;">
        <iframe src="{src}" width="100%" height="{height}" style="border:none;"></iframe>
    </div>
    """


def pdf_open_new_tab_link(pdf_bytes: bytes, page: int, label: str) -> str:
    uri = pdf_data_uri(pdf_bytes)
    href = f"{uri}#page={page}"
    return f'<a href="{href}" target="_blank" rel="noopener">{label} ↗</a>'


def find_page_block(pages: List[PageBlock], label: str) -> Optional[PageBlock]:
    for p in pages:
        if p.label == label:
            return p
    return None

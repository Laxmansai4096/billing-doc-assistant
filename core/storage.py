"""
Local, file-based persistence for the document library.

Every uploaded file is stored once (deduplicated by SHA-256 so re-uploading
the same file doesn't create a duplicate entry or re-trigger analysis), and
its full AnalysisResult is cached as JSON so re-opening it later from the
"Previously Uploaded" list is instant and free -- no LLM calls.

Layout on disk (relative to STORAGE_DIR, default "./storage"):

    storage/
        library.json          <- index of all records
        files/<id>.<ext>       <- original uploaded bytes
        analysis/<id>.json     <- cached AnalysisResult.to_dict()

This is intentionally dependency-free (just stdlib json/hashlib/uuid) so it
works out of the box for a single-user / local deployment. For a shared
multi-user deployment, swap this module for a real database -- every
function here has a narrow, self-contained interface so that's a drop-in
replacement.
"""

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any

from core.models import AnalysisResult, analysis_result_from_dict
from core.extraction import convert_to_pdf_bytes

STORAGE_DIR = os.getenv("BILLING_APP_STORAGE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage"))
FILES_DIR = os.path.join(STORAGE_DIR, "files")
ANALYSIS_DIR = os.path.join(STORAGE_DIR, "analysis")
LIBRARY_PATH = os.path.join(STORAGE_DIR, "library.json")


def _ensure_dirs():
    os.makedirs(FILES_DIR, exist_ok=True)
    os.makedirs(ANALYSIS_DIR, exist_ok=True)


def _load_library_raw() -> List[Dict[str, Any]]:
    _ensure_dirs()
    if not os.path.exists(LIBRARY_PATH):
        return []
    try:
        with open(LIBRARY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_library_raw(records: List[Dict[str, Any]]):
    _ensure_dirs()
    with open(LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def list_library() -> List[Dict[str, Any]]:
    """Most-recently-uploaded first."""
    records = _load_library_raw()
    return sorted(records, key=lambda r: r.get("uploaded_at", ""), reverse=True)


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    for r in _load_library_raw():
        if r["id"] == record_id:
            return r
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add_or_get_record(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Adds a new library entry for this file, or returns the existing one
    if a file with identical content was already uploaded before."""
    digest = _sha256(file_bytes)
    records = _load_library_raw()

    for r in records:
        if r.get("sha256") == digest:
            return r

    source_ext = os.path.splitext(filename)[1].lower() or ".bin"
    if source_ext not in {".pdf", ".docx", ".doc", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf", ".txt", ".bin"}:
        source_ext = ".bin"

    converted_pdf_bytes = convert_to_pdf_bytes(file_bytes, filename)
    doc_type = "pdf" if converted_pdf_bytes or source_ext == ".pdf" else ("docx" if source_ext in {".docx", ".doc"} else "other")
    record_id = str(uuid.uuid4())

    _ensure_dirs()
    file_path = os.path.join(FILES_DIR, f"{record_id}{source_ext if source_ext != '.pdf' else '.pdf'}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    if converted_pdf_bytes:
        with open(os.path.join(FILES_DIR, f"{record_id}.pdf"), "wb") as f:
            f.write(converted_pdf_bytes)

    record = {
        "id": record_id,
        "filename": filename,
        "source_ext": source_ext,
        "doc_type": doc_type,
        "sha256": digest,
        "size_bytes": len(file_bytes),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "analyzed": False,
    }
    records.append(record)
    _save_library_raw(records)
    return record


def mark_analyzed(record_id: str, analysis: AnalysisResult):
    with open(os.path.join(ANALYSIS_DIR, f"{record_id}.json"), "w", encoding="utf-8") as f:
        json.dump(analysis.to_dict(), f)

    records = _load_library_raw()
    for r in records:
        if r["id"] == record_id:
            r["analyzed"] = True
            r["analyzed_at"] = datetime.now().isoformat(timespec="seconds")
    _save_library_raw(records)


def load_analysis(record_id: str) -> Optional[AnalysisResult]:
    path = os.path.join(ANALYSIS_DIR, f"{record_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return analysis_result_from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError, KeyError):
        return None


def get_file_bytes(record_id: str) -> Optional[bytes]:
    record = get_record(record_id)
    if not record:
        return None
    pdf_path = os.path.join(FILES_DIR, f"{record_id}.pdf")
    if os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            return f.read()
    source_ext = record.get("source_ext", ".docx")
    path = os.path.join(FILES_DIR, f"{record_id}{source_ext}")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def get_file_path(record_id: str) -> Optional[str]:
    record = get_record(record_id)
    if not record:
        return None
    pdf_path = os.path.join(FILES_DIR, f"{record_id}.pdf")
    if os.path.exists(pdf_path):
        return pdf_path
    source_ext = record.get("source_ext", ".docx")
    path = os.path.join(FILES_DIR, f"{record_id}{source_ext}")
    return path if os.path.exists(path) else None


def delete_record(record_id: str):
    records = _load_library_raw()
    records = [r for r in records if r["id"] != record_id]
    _save_library_raw(records)

    for directory, ext_lookup in ((FILES_DIR, True), (ANALYSIS_DIR, False)):
        for ext in (".pdf", ".docx", ".doc", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf", ".txt", ".bin", ".json"):
            path = os.path.join(directory, f"{record_id}{ext}")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

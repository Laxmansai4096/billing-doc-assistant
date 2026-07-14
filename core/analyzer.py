"""
Orchestrates the full pipeline: extract -> batch -> LLM extract -> merge ->
consolidate -> ledger. Exposes a single `analyze_document` function with an
optional `progress_cb(fraction: float, message: str)` callback so the UI can
show a live progress bar.
"""

from typing import List, Optional, Callable
import base64
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.extraction import extract_document
from core.llm_engine import (
    get_client, get_chat_model, build_batches, extract_from_batch,
    merge_batch_results, consolidate_executive_summary, build_ledger,
)
from core.models import AnalysisResult
from core.config import validate_env, get_ocr_dpi, get_ocr_retries
from core.logger import get_logger


logger = get_logger()


def perform_ocr_on_pdf_page(pdf_path: str, page_num: int, client, model) -> str:
    """Renders a PDF page to a PNG image and sends it to the multimodal LLM for OCR transcription.

    This function includes basic retries and respects `OCR_DPI` and `OCR_RETRY_COUNT` from config.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("pymupdf (fitz) not installed — OCR unavailable")
        raise RuntimeError("The 'pymupdf' library is required to perform OCR on scanned PDF pages. Please run 'pip install pymupdf'.")

    dpi = get_ocr_dpi()
    retries = get_ocr_retries()

    # Render page to image bytes
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        doc.close()
    except Exception as e:
        logger.exception("Failed to render PDF page %s for OCR: %s", page_num, e)
        raise

    # Encode image bytes to base64
    b64_image = base64.b64encode(img_bytes).decode("utf-8")

    system_prompt = (
        "You are a professional financial OCR transcription tool. "
        "Transcribe all text from the provided page image. "
        "Strictly preserve all text characters, numbers, and layout structures (especially tables). "
        "Do not add any preamble, greeting, markdown code fences, or explanation. Return ONLY the transcribed text."
    )

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            logger.debug("OCR attempt %d for %s page %d", attempt, pdf_path, page_num)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}]},
                ],
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
            last_err = RuntimeError("OCR returned empty transcription")
        except Exception as e:
            logger.warning("OCR attempt %d failed for page %d: %s", attempt, page_num, e)
            last_err = e
            time.sleep(min(2 ** attempt, 10))

    logger.error("OCR failed after %d attempts for page %d: %s", retries, page_num, last_err)
    raise last_err


def analyze_document(
    path: str,
    filename: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
 ) -> AnalysisResult:

    def report(frac, msg):
        if progress_cb:
            progress_cb(frac, msg)

    report(0.05, "Extracting text and tables from the document...")
    pages, has_text, doc_type = extract_document(path, filename)

    client = get_client()
    model = get_chat_model()

    warnings: List[str] = []
    
    # If the document is a PDF and has pages with missing/empty text, run OCR on them in parallel
    if doc_type == "pdf":
        pages_to_ocr = [p for p in pages if not p.text.strip()]
        if pages_to_ocr:
            total_ocr = len(pages_to_ocr)
            completed_ocr = 0
            
            def run_ocr(page_block):
                try:
                    ocr_text = perform_ocr_on_pdf_page(path, page_block.page_number, client, model)
                    return page_block, ocr_text, None
                except Exception as e:
                    return page_block, "", f"OCR failed on Page {page_block.page_number}: {e}"
            
            with ThreadPoolExecutor(max_workers=min(10, total_ocr)) as executor:
                futures = {executor.submit(run_ocr, p): p for p in pages_to_ocr}
                for future in as_completed(futures):
                    p_block, ocr_text, err = future.result()
                    if ocr_text.strip():
                        p_block.text = ocr_text
                        has_text = True
                    if err:
                        warnings.append(err)
                    completed_ocr += 1
                    frac = 0.05 + 0.1 * (completed_ocr / total_ocr)
                    report(frac, f"Running OCR on scanned pages ({completed_ocr}/{total_ocr})...")

    if not has_text:
        warnings.append(
            "No extractable text was found in this document. Please check if the file "
            "is corrupted or contains unreadable scanned content."
        )

    report(0.15, "Splitting document into analysis batches...")
    batches = build_batches(pages)

    if not batches:
        warnings.append("No non-empty content was found to analyze.")
        return AnalysisResult(
            filename=filename, pages=pages, summary_points=[], executive_summary="",
            billing_items=[], stated_totals=[], category_rows=[], reconciliations=[],
            warnings=warnings,
        )

    batch_results = [None] * len(batches)
    total_batches = len(batches)
    completed_batches = 0
    
    def process_batch(index, batch):
        page_range = f"{batch[0].label} – {batch[-1].label}" if len(batch) > 1 else batch[0].label
        try:
            res = extract_from_batch(client, model, batch)
            return index, res, None
        except Exception as e:
            return index, {}, f"Extraction failed for {page_range}: {e}"

    with ThreadPoolExecutor(max_workers=min(10, total_batches)) as executor:
        futures = {executor.submit(process_batch, i, batch): i for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            idx, res, err = future.result()
            batch_results[idx] = res
            if err:
                warnings.append(err)
            completed_batches += 1
            frac = 0.15 + 0.6 * (completed_batches / total_batches)
            report(frac, f"Analyzing page batches ({completed_batches}/{total_batches})...")

    report(0.78, "Merging extracted points and billing items...")
    summary_points, billing_items, stated_totals, merge_warnings = merge_batch_results(batch_results)
    warnings.extend(merge_warnings)

    report(0.87, "Writing executive summary...")
    executive_summary = consolidate_executive_summary(client, model, summary_points)

    report(0.95, "Building ledger and reconciling totals...")
    category_rows, reconciliations = build_ledger(billing_items, stated_totals)

    report(1.0, "Done.")

    return AnalysisResult(
        filename=filename,
        pages=pages,
        summary_points=summary_points,
        executive_summary=executive_summary,
        billing_items=billing_items,
        stated_totals=stated_totals,
        category_rows=category_rows,
        reconciliations=reconciliations,
        warnings=warnings,
    )

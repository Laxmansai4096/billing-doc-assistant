"""
LLM orchestration layer.

Strategy
--------
Billing documents need *completeness* (every line item must be found),
not similarity search -- so unlike a typical RAG app we do NOT embed and
retrieve. Instead we walk the whole document in ordered batches of pages
("map"), ask the model to extract everything relevant from each batch,
then merge + reconcile in plain Python ("reduce"). A final short LLM call
turns the merged bullet points into a readable executive summary.
"""

import json
import os
import re
from collections import defaultdict
from typing import List, Dict, Any, Tuple

from openai import OpenAI

from core.models import (
    PageBlock, SummaryPoint, BillingItem, StatedTotal,
    LedgerCategoryRow, LedgerReconciliation,
)

MAX_CHARS_PER_BATCH = 9000  # keeps prompt + completion comfortably within context
CATEGORY_CHOICES = ["Scope", "Payment Terms", "Legal", "Risk", "Timeline", "Compliance", "Other"]


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

def get_client() -> OpenAI:
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("AZURE_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set AZURE_OPENAI_API_KEY (or OPENAI_API_KEY) in your .env file."
        )
    kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def get_chat_model() -> str:
    return os.getenv("CHAT_MODEL", "gpt-4o-mini")


# --------------------------------------------------------------------------
# Batching
# --------------------------------------------------------------------------

def build_batches(pages: List[PageBlock], max_chars: int = MAX_CHARS_PER_BATCH) -> List[List[PageBlock]]:
    batches: List[List[PageBlock]] = []
    current: List[PageBlock] = []
    current_len = 0

    for page in pages:
        if not page.text.strip():
            continue
        page_len = len(page.text)
        if current and current_len + page_len > max_chars:
            batches.append(current)
            current = []
            current_len = 0
        current.append(page)
        current_len += page_len

    if current:
        batches.append(current)

    # Guarantee huge single pages still form their own batch instead of being dropped
    return batches


def _tag_batch(batch: List[PageBlock]) -> str:
    parts = []
    for page in batch:
        parts.append(f"[[{page.label}]]\n{page.text}\n[[/{page.label}]]")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------

def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Last resort: grab the outermost {...} block
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


EXTRACTION_SYSTEM_PROMPT = """You are a meticulous financial and legal document analyst.

You will be given one or more tagged pages/sections from a single project billing document
(the document mixes legal terms, scope/policy language, and billing/invoice details, often
inside [TABLE]...[/TABLE] blocks using " | " as a column separator).

Extract THREE things and return them as a single strict JSON object, and nothing else
(no markdown fences, no commentary):

{
  "summary_points": [
    {"point": "<concise important fact, term, obligation, deadline, or risk>",
     "category": "<one of: Scope, Payment Terms, Legal, Risk, Timeline, Compliance, Other>",
     "pages": ["<exact page/section label as given, e.g. 'Page 3'>"]}
  ],
  "billing_items": [
    {"heading": "<short category such as Human Resources, Cloud Infrastructure, UI/UX Design, Full Stack Engineering, QA/Testing, Project Management, Miscellaneous, etc — infer a sensible heading from context>",
     "description": "<line item description as written>",
     "quantity": <number or null>,
     "unit_price": <number or null>,
     "amount": <number, the line total — REQUIRED if this is a billing row>,
     "currency": "<currency code or symbol as it appears, e.g. USD, INR, $, ₹ — default 'USD' only if truly ambiguous>",
     "page": "<exact page/section label>"}
  ],
  "stated_totals": [
    {"label": "<e.g. 'Subtotal', 'Tax', 'Grand Total', 'Total Amount Due'>",
     "amount": <number>,
     "currency": "<currency code or symbol>",
     "page": "<exact page/section label>"}
  ]
}

Rules:
- Only extract billing_items that have a clear numeric amount charged. Do not invent numbers.
- Every billing_items and stated_totals row MUST have a numeric "amount" (never null for amount).
- summary_points should capture important legal terms, policies, obligations, deadlines, and risks
  — NOT billing line items (those belong in billing_items).
- Use the exact page/section label text given in the [[...]] tags for the "page"/"pages" fields.
- If a page/section has nothing relevant, simply omit it — do not fabricate content.
- If there are no billing rows or totals on these pages, return empty lists for those keys.
- Output ONLY the JSON object.
"""


def extract_from_batch(client: OpenAI, model: str, batch: List[PageBlock]) -> Dict[str, Any]:
    tagged_text = _tag_batch(batch)
    user_prompt = f"Document pages/sections to analyze:\n\n{tagged_text}"

    def _call(with_json_mode: bool):
        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        if with_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    try:
        response = _call(with_json_mode=True)
    except Exception:
        response = _call(with_json_mode=False)

    raw = response.choices[0].message.content or "{}"
    return _safe_json_loads(raw)


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------

def normalize_currency(curr: str) -> str:
    """Standardizes common currency symbols and codes to standard 3-letter strings."""
    if not curr:
        return "USD"
    c = curr.strip().upper()
    if not c:
        return "USD"

    mapping = {
        "$": "USD",
        "USD": "USD",
        "U.S.D.": "USD",
        "US DOLLAR": "USD",
        "US DOLLARS": "USD",
        
        "₹": "INR",
        "INR": "INR",
        "RS": "INR",
        "RS.": "INR",
        "RUPEES": "INR",
        
        "€": "EUR",
        "EUR": "EUR",
        "EURO": "EUR",
        "EUROS": "EUR",
        
        "£": "GBP",
        "GBP": "GBP",
        "POUND": "GBP",
        "POUNDS": "GBP",
    }
    
    # Check exact mapping
    if c in mapping:
        return mapping[c]
        
    # Check substring mapping (e.g. "US $" -> "USD")
    for key, val in mapping.items():
        if key in c or c in key:
            return val
            
    return c


def merge_batch_results(batch_results: List[Dict[str, Any]]) -> Tuple[List[SummaryPoint], List[BillingItem], List[StatedTotal], List[str]]:
    summary_points: List[SummaryPoint] = []
    billing_items: List[BillingItem] = []
    stated_totals: List[StatedTotal] = []
    warnings: List[str] = []

    for result in batch_results:
        for sp in result.get("summary_points", []) or []:
            try:
                summary_points.append(SummaryPoint(
                    point=str(sp.get("point", "")).strip(),
                    category=sp.get("category") if sp.get("category") in CATEGORY_CHOICES else "Other",
                    pages=[str(p) for p in (sp.get("pages") or [])],
                ))
            except Exception:
                warnings.append("Skipped a malformed summary point during extraction.")

        for bi in result.get("billing_items", []) or []:
            amount = bi.get("amount")
            if amount is None:
                warnings.append(f"Skipped a billing item with no amount: {bi.get('description', '(no description)')}")
                continue
            try:
                billing_items.append(BillingItem(
                    heading=str(bi.get("heading", "Uncategorized")).strip() or "Uncategorized",
                    description=str(bi.get("description", "")).strip(),
                    quantity=_to_float(bi.get("quantity")),
                    unit_price=_to_float(bi.get("unit_price")),
                    amount=float(amount),
                    currency=normalize_currency(str(bi.get("currency", "USD"))),
                    page=str(bi.get("page", "Unknown")),
                ))
            except (TypeError, ValueError):
                warnings.append(f"Skipped a billing item with an unparseable amount: {bi.get('description', '')}")

        for st_ in result.get("stated_totals", []) or []:
            amount = st_.get("amount")
            if amount is None:
                continue
            try:
                stated_totals.append(StatedTotal(
                    label=str(st_.get("label", "Total")).strip() or "Total",
                    amount=float(amount),
                    currency=normalize_currency(str(st_.get("currency", "USD"))),
                    page=str(st_.get("page", "Unknown")),
                ))
            except (TypeError, ValueError):
                warnings.append("Skipped a stated total with an unparseable amount.")

    return summary_points, billing_items, stated_totals, warnings


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Executive summary consolidation
# --------------------------------------------------------------------------

CONSOLIDATION_SYSTEM_PROMPT = """You are a senior project analyst writing an executive brief for a busy stakeholder.
You will receive a list of extracted bullet points (with categories) from a project billing/contract document.
Return a polished markdown briefing with the following sections (use the exact headers):

## Document Overview
Write a concise 2-3 sentence paragraph summarizing the document's main idea, purpose, parties involved, and overall context. Do NOT use bullet points in this section.

## Key Commercial Terms
- 3-5 short bullets

## Legal, Risk & Obligations
- 3-5 short bullets

## Important Dates & Milestones
- 3-5 short bullets

Keep the content factual, concise, and professional. Do not invent facts not present in the source points. No code fences."""


def _fallback_structured_summary(summary_points: List[SummaryPoint]) -> str:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for sp in summary_points:
        grouped[sp.category].append(sp.point)

    sections = ["## Document Overview"]
    top_points = [sp.point for sp in summary_points[:2]]
    if top_points:
        sections.append(f"This document outlines key project terms, including {', '.join(top_points)}.")
    else:
        sections.append("This document contains project billing and agreement details.")

    def add_section(title: str, categories: List[str]) -> None:
        bullets = []
        for category in categories:
            bullets.extend(grouped.get(category, [])[:3])
        if not bullets:
            return
        sections.append("")
        sections.append(f"## {title}")
        sections.extend(f"- {bullet}" for bullet in bullets[:5])

    add_section("Key Commercial Terms", ["Scope", "Payment Terms", "Other"])
    add_section("Legal, Risk & Obligations", ["Legal", "Risk", "Compliance"])
    add_section("Important Dates & Milestones", ["Timeline"])
    return "\n".join(sections).strip()


def consolidate_executive_summary(client: OpenAI, model: str, summary_points: List[SummaryPoint]) -> str:
    if not summary_points:
        return "## Document Overview\n\nNo summary points could be extracted from this document."

    bullets = "\n".join(f"- ({sp.category}) {sp.point}" for sp in summary_points[:120])
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": CONSOLIDATION_SYSTEM_PROMPT},
                {"role": "user", "content": bullets},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        raw = raw.replace("```markdown", "").replace("```", "").strip()
        return raw or _fallback_structured_summary(summary_points)
    except Exception as e:
        return _fallback_structured_summary(summary_points)


# --------------------------------------------------------------------------
# Ledger / reconciliation (pure python, no LLM)
# --------------------------------------------------------------------------

def build_ledger(billing_items: List[BillingItem], stated_totals: List[StatedTotal]) -> Tuple[List[LedgerCategoryRow], List[LedgerReconciliation]]:
    # Category subtotals, grouped by currency
    category_sums: Dict[Tuple[str, str], float] = defaultdict(float)
    category_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    currency_totals: Dict[str, float] = defaultdict(float)

    for item in billing_items:
        key = (item.currency, item.heading)
        category_sums[key] += item.amount
        category_counts[key] += 1
        currency_totals[item.currency] += item.amount

    category_rows = [
        LedgerCategoryRow(
            heading=heading,
            currency=currency,
            computed_total=round(total, 2),
            item_count=category_counts[(currency, heading)],
        )
        for (currency, heading), total in sorted(category_sums.items(), key=lambda kv: -kv[1])
    ]

    # Reconciliation: for each currency present in billing items, find the best
    # candidate "grand total" among stated_totals (prefer labels containing
    # 'grand total' or 'total due' or 'total amount', else the largest 'total'-ish label).
    reconciliations: List[LedgerReconciliation] = []

    def score_label(label: str) -> int:
        l = label.lower()
        if "grand total" in l or "total due" in l or "total amount" in l or "amount due" in l:
            return 3
        if l.strip() == "total":
            return 2
        if "total" in l:
            return 1
        return 0

    currencies = set(currency_totals.keys()) | {st.currency for st in stated_totals}
    for currency in currencies:
        computed = round(currency_totals.get(currency, 0.0), 2)
        candidates = [st for st in stated_totals if st.currency == currency]
        candidates_scored = sorted(candidates, key=lambda st: (score_label(st.label), st.amount), reverse=True)

        best = candidates_scored[0] if candidates_scored else None

        if best is None:
            reconciliations.append(LedgerReconciliation(
                currency=currency, computed_total=computed, stated_total_label=None,
                stated_total_amount=None, difference=None, status="No stated total found",
            ))
            continue

        diff = round(computed - best.amount, 2)
        tolerance = max(0.01, abs(best.amount) * 0.001)
        status = "Match" if abs(diff) <= tolerance else "Mismatch"

        reconciliations.append(LedgerReconciliation(
            currency=currency,
            computed_total=computed,
            stated_total_label=best.label,
            stated_total_amount=best.amount,
            difference=diff,
            status=status,
        ))

    return category_rows, reconciliations

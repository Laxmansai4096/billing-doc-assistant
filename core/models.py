"""
Typed data structures shared across the extraction, LLM and UI layers.

Kept as plain dataclasses (no pydantic dependency) so the project has a
minimal footprint. Every object exposes `.to_dict()` for easy use with
pandas / JSON / Streamlit tables.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class PageBlock:
    """A single 'locatable' unit of the source document (a real PDF page,
    a detected DOCX page, a heading-based DOCX section, or a fallback
    fixed-size chunk)."""
    index: int                # 1-based sequential index, always present
    page_number: Optional[int]  # real page number if known (PDF, or DOCX w/ explicit breaks)
    label: str                 # human readable label e.g. "Page 3" / "Section: Payment Terms"
    text: str
    is_true_page: bool         # True if `page_number` is a reliable physical page

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryPoint:
    point: str
    category: str               # Scope | Payment Terms | Legal | Risk | Timeline | Other
    pages: List[str] = field(default_factory=list)   # list of labels e.g. ["Page 3", "Page 4"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BillingItem:
    heading: str                # e.g. "Human Resources", "Cloud Infrastructure", "UI/UX", "Full Stack Engineering"
    description: str
    quantity: Optional[float]
    unit_price: Optional[float]
    amount: Optional[float]
    currency: str
    page: str                   # label e.g. "Page 5"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StatedTotal:
    label: str                  # e.g. "Total Amount Due", "Grand Total", "Subtotal"
    amount: Optional[float]
    currency: str
    page: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerCategoryRow:
    heading: str
    currency: str
    computed_total: float
    item_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerReconciliation:
    currency: str
    computed_total: float
    stated_total_label: Optional[str]
    stated_total_amount: Optional[float]
    difference: Optional[float]
    status: str                 # "Match" | "Mismatch" | "No stated total found"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisResult:
    filename: str
    pages: List[PageBlock]
    summary_points: List[SummaryPoint]
    executive_summary: str
    billing_items: List[BillingItem]
    stated_totals: List[StatedTotal]
    category_rows: List[LedgerCategoryRow]
    reconciliations: List[LedgerReconciliation]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "pages": [p.to_dict() for p in self.pages],
            "summary_points": [s.to_dict() for s in self.summary_points],
            "executive_summary": self.executive_summary,
            "billing_items": [b.to_dict() for b in self.billing_items],
            "stated_totals": [t.to_dict() for t in self.stated_totals],
            "category_rows": [c.to_dict() for c in self.category_rows],
            "reconciliations": [r.to_dict() for r in self.reconciliations],
            "warnings": self.warnings,
        }


def analysis_result_from_dict(d: Dict[str, Any]) -> "AnalysisResult":
    """Reconstructs a full AnalysisResult (with real dataclass instances,
    not plain dicts) from the JSON produced by `AnalysisResult.to_dict()`.
    Used to load a previously analyzed document back out of storage
    without re-running any LLM calls."""
    return AnalysisResult(
        filename=d.get("filename", ""),
        pages=[PageBlock(**p) for p in d.get("pages", [])],
        summary_points=[SummaryPoint(**s) for s in d.get("summary_points", [])],
        executive_summary=d.get("executive_summary", ""),
        billing_items=[BillingItem(**b) for b in d.get("billing_items", [])],
        stated_totals=[StatedTotal(**t) for t in d.get("stated_totals", [])],
        category_rows=[LedgerCategoryRow(**c) for c in d.get("category_rows", [])],
        reconciliations=[LedgerReconciliation(**r) for r in d.get("reconciliations", [])],
        warnings=d.get("warnings", []),
    )

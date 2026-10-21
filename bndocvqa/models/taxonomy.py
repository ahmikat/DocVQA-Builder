"""Taxonomy v4 — the single source of truth for axis codes and names.

Definitions are copied verbatim from the project specification; do not
paraphrase them, because prompts, validation and exports all depend on them.
"""
from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "v4"


@dataclass(frozen=True)
class Axis:
    code: str
    name: str
    family: str  # "B" (evidence and verification) or "C" (document capabilities)
    definition: str


AXES: tuple[Axis, ...] = (
    Axis("B01", "Direct evidence reading", "B",
         "Identify a specific fact or number explicitly stated in the document."),
    Axis("B03", "Evidence sufficiency and abstention", "B",
         "Determine that the required information is absent after reviewing the relevant complete document."),
    Axis("B04", "Claim verification", "B",
         "Classify a specific claim as supported, contradicted, or insufficient information."),
    Axis("C01", "Structural locating and layout", "C",
         "Understand headings, subsections, footnotes, checkbox states, or layout hierarchy."),
    Axis("C02", "Table interpretation", "C",
         "Correctly associate table row headers, column headers, units, and cell values."),
    Axis("C03", "Charts and infographics", "C",
         "Interpret graphical bars, pie charts, symbols, and legends."),
    Axis("C04", "Maps and spatial relations", "C",
         "Understand directions, proximity, boundaries, and spatial relationships."),
    Axis("C05", "Counting", "C",
         "Count a clearly defined set of items under a specified rule rather than copying a printed total."),
    Axis("C06", "Filtering and set selection", "C",
         "Identify all entries satisfying a specified condition."),
    Axis("C07", "Comparison and ranking", "C",
         "Compare two or more values and identify maxima or minima, including ties."),
    Axis("C08", "Arithmetic and aggregation", "C",
         "Perform addition, subtraction, averaging, or other calculations using document values "
         "without assuming undocumented taxes or fees."),
    Axis("C09", "Temporal reasoning", "C",
         "Calculate durations, travel times, remaining days, or differences between dates and times."),
    Axis("C10", "Units and numerical normalization", "C",
         "Convert units such as crore to lakh or millimetres to centimetres."),
    Axis("C11", "Conditions and exceptions", "C",
         "Determine eligibility or applicability using documented conditions and exceptions."),
    Axis("C12", "Entity and record binding", "C",
         "Match information to the correct person, organization, or record."),
    Axis("C13", "Cross-element association", "C",
         "Combine information such as a table and its footnote, or an image and its textual condition."),
    Axis("C14", "Bounded synthesis", "C",
         "Combine specific information from multiple sections or paragraphs into a concise answer."),
    Axis("C15", "Amendment and conflict reconciliation", "C",
         "Determine the final applicable value or rule when original and amended provisions conflict."),
)

AXIS_BY_CODE: dict[str, Axis] = {a.code: a for a in AXES}
AXIS_CODES: tuple[str, ...] = tuple(a.code for a in AXES)


def axis_name(code: str) -> str:
    return AXIS_BY_CODE[code].name


# --- Question formats and types -------------------------------------------

# Standard five-option multiple choice (answerable questions and B03).
FORMAT_MCQ5 = "mcq5"
# Three-option claim verification schema for B04 (researcher decision, 2026-10-21).
FORMAT_VERIFY3 = "verify3"
QUESTION_FORMATS = (FORMAT_MCQ5, FORMAT_VERIFY3)

TYPE_ANSWERABLE = "answerable"
TYPE_ABSTENTION = "abstention"
TYPE_CLAIM = "claim_verification"
QUESTION_TYPES = (TYPE_ANSWERABLE, TYPE_ABSTENTION, TYPE_CLAIM)

MCQ5_LABELS = ("A", "B", "C", "D", "E")
VERIFY3_LABELS = ("A", "B", "C")

# The single canonical abstention answer for B03.
ABSTAIN_TEXT = "প্রদত্ত নথিতে উল্লেখ নেই"

# B04 outcomes in their fixed option order.
CLAIM_SUPPORTED = "সমর্থিত"
CLAIM_CONTRADICTED = "খণ্ডনকৃত"
CLAIM_INSUFFICIENT = "অপর্যাপ্ত তথ্য"
VERIFY3_OPTIONS: dict[str, str] = {
    "A": CLAIM_SUPPORTED,
    "B": CLAIM_CONTRADICTED,
    "C": CLAIM_INSUFFICIENT,
}
CLAIM_OUTCOMES = tuple(VERIFY3_OPTIONS.values())


def labels_for(fmt: str) -> tuple[str, ...]:
    return MCQ5_LABELS if fmt == FORMAT_MCQ5 else VERIFY3_LABELS


def expected_format(primary_axis: str) -> str:
    return FORMAT_VERIFY3 if primary_axis == "B04" else FORMAT_MCQ5


def expected_type(primary_axis: str) -> str:
    if primary_axis == "B03":
        return TYPE_ABSTENTION
    if primary_axis == "B04":
        return TYPE_CLAIM
    return TYPE_ANSWERABLE


def taxonomy_markdown() -> str:
    """Render the taxonomy as Markdown for prompts and docs."""
    lines = []
    for a in AXES:
        lines.append(f"- `{a.code}` — {a.name}: {a.definition}")
    return "\n".join(lines)

"""The page prompt and its response schema.

One request = one page image. Change the prompt => bump PROMPT_VERSION; the
version is stored on every generated question.
"""
from __future__ import annotations

from ..models.taxonomy import ABSTAIN_TEXT, AXES, CLAIM_CONTRADICTED, CLAIM_INSUFFICIENT, CLAIM_SUPPORTED

PROMPT_VERSION = "page-v4-reasoning"

# Prompt-only challenge cues. The canonical taxonomy codes and definitions stay
# in models.taxonomy; these cues help Gemini choose stronger page-grounded tasks.
AXIS_CHALLENGE_HINTS = {
    "B01": "Locate the right fact among similar entities, repeated values, or different sections.",
    "B03": "Prefer a subtle missing detail when related information is present; verify it is absent from this page.",
    "B04": "Use checkable relationships, conditions, exceptions, or combined facts; silence is not contradiction.",
    "C01": "Use hierarchy, field labels, footnotes, or placement to decide which information belongs where.",
    "C02": "Interpret linked rows, columns, merged or grouped headers, units, and table notes rather than just one cell.",
    "C03": "Read legends, scales, categories, trends, or graphical comparisons, not only printed labels.",
    "C04": "Connect directions, routes, boundaries, or positions when the map clearly supports them.",
    "C05": "Count a defined subset with any stated exclusions or qualifying conditions.",
    "C06": "Select entries using multiple documented conditions, thresholds, or exclusions when useful.",
    "C07": "Compare relevant subsets, periods, close values, or ties with the right units and labels.",
    "C08": "Calculate from documented values, possibly after selecting records or combining several figures.",
    "C09": "Relate dates, deadlines, durations, effective dates, or overlapping periods when unambiguous.",
    "C10": "Normalize units before interpreting or comparing the page's numerical values.",
    "C11": "Apply all relevant criteria, boundary values, restrictions, and exceptions to a concrete case.",
    "C12": "Bind each attribute to its correct person or record despite similar names or identifiers.",
    "C13": "Combine distinct elements, such as a table and footnote, chart and legend, or field and instruction.",
    "C14": "Combine specific facts from separate sections into one objectively verifiable answer.",
    "C15": "Resolve original and revised provisions using explicit precedence or effective dates on this page.",
}


def _taxonomy_prompt() -> str:
    return "\n".join(
        f"- `{axis.code}` — {axis.name}: {axis.definition} Challenge cue: {AXIS_CHALLENGE_HINTS[axis.code]}"
        for axis in AXES
    )

# Page classifications. Pages of the NO_QUESTION_TYPES kinds never get questions.
PAGE_TYPES = {
    "text": "running text: notice, letter, circular, article, law",
    "table": "mainly a table or schedule",
    "form": "a form with fields, boxes or checkboxes",
    "chart": "chart, graph, infographic or map with readable labels",
    "mixed": "several of the above",
    "cover": "title or cover page with little information",
    "blank": "empty or nearly empty page",
    "qr_or_barcode": "only a QR code, barcode or similar machine-readable mark",
    "signature_or_stamp": "only signatures, seals, stamps or initials",
    "image_only": "photo, logo or illustration without readable information",
    "unreadable": "too blurred, faint, cut off or damaged to read reliably",
}
NO_QUESTION_TYPES = {"blank", "qr_or_barcode", "signature_or_stamp", "image_only", "unreadable"}


def page_prompt(page_limit: int, document_limit: int | None = None) -> str:
    n = max(0, page_limit)
    document_rule = (f"This document has a hard maximum of {document_limit} questions across all its pages. "
                     if document_limit is not None else "")
    types = "\n".join(f"- {k}: {v}" for k, v in PAGE_TYPES.items())
    return f"""You are building a Bangla Document Visual Question Answering benchmark.
You are given ONE page image from a Bangladeshi document (government notice, form, circular, report, table,
schedule, chart, newspaper, exam material, etc.). The image is the ONLY source of truth for every question.

STEP 1 — CLASSIFY THE PAGE
Set page_type to exactly one of:
{types}
Set page_note to a short English description of what the page contains (e.g. "signature block with a round seal",
"QR code and footer only", "attendance table with 12 rows").

If page_type is blank, qr_or_barcode, signature_or_stamp, image_only or unreadable, return "questions": [] and stop.
Such pages are kept in the dataset without questions; inventing questions about them is an error.

STEP 2 — DESIGN DOCUMENT-GROUNDED QUESTIONS (only for pages with readable information)
First examine what this page actually contains: its layout, labels, records, relationships, conditions,
exceptions, and small details that could be misread. Choose the strongest questions the visible evidence supports.
Prefer medium-hard or hard questions where natural, including subtle visual distinctions or several reasoning
steps. A simple page may warrant fewer questions; keep direct-reading questions when they meaningfully test
localization, OCR, or distinguishing similar facts. Never force a taxonomy, difficulty level, or reasoning pattern.

Useful possibilities, only when supported: filter records then compare values; apply a table footnote; bind an
entity to the right row before calculating; combine a condition with an exception or date; reconcile an explicit
amendment; or connect facts from separate sections. Difficulty must come from interpreting this page, not from
obscure Bengali wording, needless complexity, or knowledge outside the image. Each question must have exactly
one clear, defensible answer under its precise wording. Check calculations, units, boundaries, and dates.

HOW MANY
{document_rule}Return AT MOST {n} questions for this page. This is a hard maximum, not a target.
A sparse page may support fewer, including zero. Do not exceed the maximum even on a dense page.
Never write a weak, trivial, ambiguous or repetitive question just to reach a number, and never ask the same fact
twice in different words.

WHAT NOT TO ASK
- Never ask about the content of a QR code or barcode; it cannot be read from the image.
- Do not ask what a signature says, what a seal or logo looks like, or about colours, fonts and decorations,
  unless that visual element carries document information (e.g. a chart legend colour, a ticked checkbox, a
  printed name under a signature).
- Do not ask about text you cannot read with certainty (blurred, cut off, overlapped by a stamp).

LANGUAGE
- Questions in natural, fluent Bangla.
- Answers and options usually in Bangla, but copy names, designations, abbreviations, units, dates, numbers and
  English terms exactly as printed, in the numeral script used on the page (Bengali ০-৯ or Arabic 0-9).
- Do not refer to "page 2" etc.; the reader sees only this one image.

TAXONOMY v4 — pick exactly ONE primary_axis per question; sub_axes only for genuinely additional capabilities
(never repeat the primary axis; B03 and B04 are never sub-axes). Use only axes the page naturally supports.
The challenge cues below are inspiration, not templates or quotas:
{_taxonomy_prompt()}
Notes: C05 counts items rather than copying a printed total (copying a total is B01). C08 uses only values on
the page and never assumes undocumented taxes or fees. C15 needs an explicit amendment/precedence on the page.

ANSWER FORMAT PER QUESTION TYPE
1. Answerable questions (B01, C01-C15): give the exact correct answer and FOUR distractors.
2. B03 (abstention): at most ONE per page, and only on a page with real content. Ask for something this
   particular page would naturally be expected to state but certainly does NOT (e.g. a notice that gives a
   date and venue but no time; a fee table with no late fee). It must be specific to this page's subject —
   never a generic question that could be asked of any page.
   The correct answer is exactly "{ABSTAIN_TEXT}". Give FOUR plausible-looking distractor values, none of which
   is stated on the page for this question. Missing does not mean zero.
3. B04 (claim verification): the question states one specific claim in quotes, e.g.
   দাবিটি যাচাই করুন: '...'. Give claim_outcome = exactly one of "{CLAIM_SUPPORTED}", "{CLAIM_CONTRADICTED}",
   "{CLAIM_INSUFFICIENT}". "{CLAIM_CONTRADICTED}" requires the page to state something incompatible with the
   claim; if the page is silent, the outcome is "{CLAIM_INSUFFICIENT}". Leave distractors empty.

DISTRACTORS (wrong options) for types 1 and 2
- Each must be demonstrably WRONG under the question's exact wording, yet plausible to a careless reader.
- Best sources: neighbouring values in the same table/section, values from another row or column, similar
  names/dates/amounts/designations on the page, wrong combinations of attributes, plausible arithmetic slips,
  misapplied conditions, footnotes or amendments. Make wrong options competitive without making them ambiguous.
- Same kind of thing as the correct answer (all dates, all amounts, all names...), similar length and form,
  same numeral script.
- No "all/none of the above", no nonsense, no two options that mean the same thing, nothing equivalent to the
  correct answer (e.g. the same number in another digit script). Do not use "{ABSTAIN_TEXT}" or any
  "not mentioned" wording as a distractor.

ALSO GIVE
- evidence_snippet: copy the short exact text, labels, or values from this page needed to verify the answer;
  for multi-part reasoning include the relevant source facts, not an invented quotation. For B03, briefly say
  what related information the page contains and why the requested detail is absent.
- rationale (Bangla, one sentence): which capability the question tests.

Return JSON matching the schema: page_type, page_note, questions."""


PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_type": {"type": "string", "enum": list(PAGE_TYPES)},
        "page_note": {"type": "string"},
        "questions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question_bn": {"type": "string"},
                "primary_axis": {"type": "string"},
                "sub_axes": {"type": "array", "items": {"type": "string"}},
                "correct_answer": {"type": "string"},
                "distractors": {"type": "array", "items": {"type": "string"}},
                "claim_outcome": {"type": "string"},
                "evidence_snippet": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["question_bn", "primary_axis", "correct_answer", "evidence_snippet"],
        }},
    },
    "required": ["page_type", "questions"],
}

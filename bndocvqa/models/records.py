"""Plain dataclass records shared by the database, services and UI."""
from __future__ import annotations

from dataclasses import dataclass, field

from .taxonomy import FORMAT_MCQ5, TYPE_ANSWERABLE

# Page processing states
PENDING = "pending"
DONE = "done"
FAILED = "failed"


@dataclass
class Document:
    document_id: str  # also its display name: doc_1, doc_2, ...
    original_filename: str
    file_path: str  # relative to data_dir
    file_hash: str
    page_count: int = 0
    imported_at: str = ""


@dataclass
class Page:
    page_id: str  # doc_1_p1
    document_id: str
    page_number: int  # 1-based
    image_path: str  # relative to data_dir
    width: int = 0
    height: int = 0
    status: str = PENDING
    error: str = ""
    content_type: str = ""  # Gemini's classification, see prompts.PAGE_TYPES
    content_note: str = ""  # e.g. why the page has no questions


@dataclass
class Option:
    label: str
    text: str


@dataclass
class Question:
    question_id: str  # doc_1_p1_q1
    document_id: str
    page_id: str
    question_number: int  # within the page
    question_bn: str = ""
    question_format: str = FORMAT_MCQ5
    question_type: str = TYPE_ANSWERABLE
    options: list[Option] = field(default_factory=list)
    correct_option: str = ""
    answer_bn: str = ""
    primary_axis: str = ""
    sub_axes: list[str] = field(default_factory=list)
    evidence_snippet: str = ""
    rationale: str = ""
    model: str = ""
    prompt_version: str = ""
    created_at: str = ""
    updated_at: str = ""
    edited: bool = False
    reviewed: bool = False  # explicitly saved in View; eligible for dataset files
    reviewed_at: str = ""

    def option_map(self) -> dict[str, str]:
        return {o.label: o.text for o in self.options}

    def option_text(self, label: str) -> str:
        return self.option_map().get(label, "")


@dataclass
class Job:
    """One Gemini request: one page."""

    job_id: str
    page_id: str
    document_id: str
    idempotency_key: str
    status: str = "queued"  # queued | running | succeeded | failed | cancelled
    attempts: int = 0
    max_attempts: int = 4
    error: str = ""
    model: str = ""
    prompt_version: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    next_attempt_at: str = ""
    result_summary: str = ""

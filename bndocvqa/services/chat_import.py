"""Validate a pasted Gemini chat batch and stage its questions for manual review."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..models.records import Option, Question, SourcePage
from ..models.taxonomy import (ABSTAIN_TEXT, AXIS_BY_CODE, FORMAT_VERIFY3, VERIFY3_OPTIONS,
                               expected_format, expected_type)
from ..models.text import fold_for_equivalence, normalize_answer
from .files import sha256_file

SCHEMA_VERSION = "gemini_chat_multipage_v1"


@dataclass
class PreparedChatImport:
    document_id: str
    document_name: str
    page_count: int
    questions: list[Question]
    existing: int
    warnings: list[str]


def _required_text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _json_object(text: str) -> dict:
    text = text.strip().lstrip("\ufeff").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if not lines[-1].strip().startswith("```"):
            raise ValueError("the Markdown JSON code fence is not closed")
        text = "\n".join(lines[1:-1])
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid or incomplete JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("the pasted JSON must be one object containing document_id and questions")
    return value


def prepare_chat_import(ctx, text: str) -> PreparedChatImport:
    data = _json_object(text)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    document_id = _required_text(data.get("document_id"), "document_id")
    doc = ctx.documents.get(document_id)
    if doc is None:
        raise ValueError(f"{document_id} is not in this workspace; import the source document first")
    original = ctx.abs_path(doc.file_path)
    if not original.is_file() or sha256_file(original) != doc.file_hash:
        raise ValueError(f"{document_id}: the stored source document is missing or differs from its recorded hash")
    raw = data.get("questions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("questions must be a non-empty array")
    pages = {p.page_id: p for p in ctx.pages.for_document(document_id)}
    questions, warnings, fingerprints = [], [], set()
    for index, item in enumerate(raw, 1):
        prefix = f"question {index}"
        if not isinstance(item, dict):
            raise ValueError(f"{prefix} must be an object")
        try:
            question_bn = _required_text(item.get("question_bn"), "question_bn")
            axis = _required_text(item.get("primary_axis"), "primary_axis")
            if axis not in AXIS_BY_CODE:
                raise ValueError(f"unknown primary_axis {axis}")
            fmt, qtype = expected_format(axis), expected_type(axis)
            if item.get("question_format") != fmt or item.get("question_type") != qtype:
                raise ValueError(f"{axis} requires question_format={fmt}, question_type={qtype}")
            sub = item.get("sub_axes")
            if not isinstance(sub, list) or any(not isinstance(a, str) or a not in AXIS_BY_CODE or
                                                 a in (axis, "B03", "B04") for a in sub) or len(sub) != len(set(sub)):
                raise ValueError("sub_axes must contain distinct valid additional axes (excluding B03/B04)")
            raw_sources = item.get("source_pages")
            if not isinstance(raw_sources, list) or not raw_sources:
                raise ValueError("source_pages must list every page needed to answer")
            sources = []
            for source in raw_sources:
                if not isinstance(source, dict):
                    raise ValueError("each source_pages item must be an object")
                page_id = _required_text(source.get("page_id"), "source page_id")
                if page_id not in pages:
                    raise ValueError(f"source page {page_id} is not in {document_id}")
                if any(s.page_id == page_id for s in sources):
                    raise ValueError(f"source page {page_id} is repeated")
                if not ctx.abs_path(pages[page_id].image_path).is_file():
                    raise ValueError(f"page image is missing: {page_id}")
                used_for = source.get("used_for", "")
                if not isinstance(used_for, str):
                    raise ValueError("source used_for must be text")
                sources.append(SourcePage(page_id, _required_text(source.get("evidence_snippet"),
                                                                   "source evidence_snippet"),
                                          used_for.strip()))
            if axis == "B03" and len(sources) > 1:
                warnings.append(f"{prefix}: B03 spans pages; verify the requested detail is absent from the stated scope")
            raw_steps = item.get("reasoning_steps")
            if not isinstance(raw_steps, list) or any(not isinstance(s, str) or not s.strip() for s in raw_steps):
                raise ValueError("reasoning_steps must be an array of non-empty text steps")
            options = item.get("options")
            labels = "ABC" if fmt == FORMAT_VERIFY3 else "ABCDE"
            if not isinstance(options, dict) or set(options) != set(labels):
                raise ValueError(f"options must contain exactly {', '.join(labels)}")
            option_texts = [_required_text(options[lb], f"option {lb}") for lb in labels]
            if len({fold_for_equivalence(t) for t in option_texts}) != len(labels):
                raise ValueError("options must be distinct, including equivalent numeral spellings")
            if fmt == FORMAT_VERIFY3 and options != VERIFY3_OPTIONS:
                raise ValueError("B04 options must be the fixed supported/contradicted/insufficient labels")
            correct = item.get("correct_option")
            if correct not in labels:
                raise ValueError("correct_option must be an option label")
            answer = _required_text(item.get("answer_bn"), "answer_bn")
            if answer != options[correct]:
                raise ValueError("answer_bn must exactly match options[correct_option]")
            if axis == "B03" and answer != ABSTAIN_TEXT:
                raise ValueError(f"B03 correct answer must be exactly {ABSTAIN_TEXT}")
            if axis != "B03" and axis != "B04" and answer == ABSTAIN_TEXT:
                raise ValueError("answerable questions cannot use the abstention answer")
            rationale = _required_text(item.get("rationale"), "rationale")
            key_data = [document_id, question_bn, [s.page_id for s in sources], axis, answer]
            fingerprint = hashlib.sha256(json.dumps(key_data, ensure_ascii=False, separators=(",", ":"))
                                          .encode("utf-8")).hexdigest()
            if fingerprint in fingerprints:
                raise ValueError("this question is repeated in the pasted batch")
            fingerprints.add(fingerprint)
            q = Question(question_id="", document_id=document_id, page_id=sources[0].page_id,
                         question_number=0, question_bn=question_bn, question_format=fmt,
                         question_type=qtype, options=[Option(lb, options[lb]) for lb in labels],
                         source_pages=sources, reasoning_steps=[s.strip() for s in raw_steps],
                         correct_option=correct, answer_bn=answer, primary_axis=axis, sub_axes=sub,
                         evidence_snippet=" | ".join(f"{s.page_id}: {s.evidence_snippet}" for s in sources),
                         rationale=rationale, model="Gemini chat (model unspecified)",
                         prompt_version=SCHEMA_VERSION, import_key=fingerprint)
            questions.append(q)
        except ValueError as exc:
            raise ValueError(f"{prefix}: {exc}") from exc
    existing_keys = {r[0] for r in ctx.db.query(
        "SELECT import_key FROM questions WHERE document_id=? AND import_key<>''", (document_id,))}
    existing_texts = {normalize_answer(r[0]) for r in ctx.db.query(
        "SELECT question_bn FROM questions WHERE document_id=?", (document_id,))}
    existing = sum(q.import_key in existing_keys or normalize_answer(q.question_bn) in existing_texts for q in questions)
    return PreparedChatImport(document_id, doc.original_filename, doc.page_count, questions, existing, warnings)


def stage_chat_import(ctx, prepared: PreparedChatImport) -> list[str]:
    """Insert new unreviewed questions atomically; no existing question is replaced."""
    if ctx.documents.get(prepared.document_id) is None:
        raise ValueError(f"{prepared.document_id} is no longer in the workspace")
    created = []
    with ctx.db.tx() as con:
        for q in prepared.questions:
            if con.execute("SELECT 1 FROM questions WHERE import_key=? OR "
                           "(document_id=? AND question_bn=?) LIMIT 1",
                           (q.import_key, q.document_id, q.question_bn)).fetchone():
                continue
            for source in q.source_pages:
                if not con.execute("SELECT 1 FROM pages WHERE page_id=? AND document_id=?",
                                   (source.page_id, q.document_id)).fetchone():
                    raise ValueError(f"source page {source.page_id} is no longer in {q.document_id}")
            q.question_number = con.execute("SELECT COALESCE(MAX(question_number),0)+1 FROM questions WHERE page_id=?",
                                            (q.page_id,)).fetchone()[0]
            q.question_id = f"{q.page_id}_chat_{q.import_key[:12]}"
            ctx.questions._insert(con, q)
            created.append(q.question_id)
    return created

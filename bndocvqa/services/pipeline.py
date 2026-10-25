"""Processing: one Gemini request per page, returning that page's questions.

A page job is idempotent: its result replaces the page's questions in one
transaction, so retrying a page never duplicates anything. A document is
finished when every page is done.
"""
from __future__ import annotations

import hashlib
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Callable

from .. import prompts as P
from ..models.records import DONE, FAILED, PENDING, Job
from ..models.taxonomy import TYPE_ABSTENTION
from ..models.text import normalize_answer
from .context import AppContext
from .gemini.parsing import as_str, require_list
from .gemini.provider import ImagePart, Provider, ResponseBlocked, Usage
from .mcq import build_question
from .question_limits import max_questions_for_document

log = logging.getLogger(__name__)


@dataclass
class StageOutcome:
    summary: str
    usage: Usage
    raw: str = ""


class Pipeline:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # -- queueing ---------------------------------------------------------
    def process_document(self, document_id: str) -> list[Job]:
        """Queue every page of the document that is not done yet."""
        return [self.enqueue_page(p.page_id) for p in self.ctx.pages.for_document(document_id) if p.status != DONE]

    def enqueue_page(self, page_id: str) -> Job:
        page = self.ctx.pages.get(page_id)
        model = self.ctx.settings.gemini_model
        key = hashlib.sha256(f"{page_id}|{P.PROMPT_VERSION}|{model}".encode()).hexdigest()[:24]
        job = Job(job_id="J" + uuid.uuid4().hex[:12], page_id=page_id, document_id=page.document_id,
                  idempotency_key=key, max_attempts=self.ctx.settings.gemini_max_attempts, model=model,
                  prompt_version=P.PROMPT_VERSION)
        job, _ = self.ctx.jobs.enqueue(job)
        if page.status == FAILED:
            self.ctx.pages.set_status(page_id, PENDING)
        return job

    # -- execution --------------------------------------------------------
    def run(self, job: Job, provider: Provider, cancelled: Callable[[], bool]) -> StageOutcome:
        page = self.ctx.pages.get(job.page_id)
        doc = self.ctx.documents.get(page.document_id)
        cap = max_questions_for_document(doc.page_count)
        if page.status == DONE and self.ctx.db.query_one(
                "SELECT COUNT(*) FROM questions WHERE page_id=? AND reviewed=1", (page.page_id,))[0]:
            return StageOutcome("existing page kept: saved questions", Usage())
        other_count = self.ctx.db.query_one(
            "SELECT COUNT(*) FROM questions WHERE document_id=? AND page_id<>?",
            (page.document_id, page.page_id))[0]
        if page.status == DONE and other_count + self.ctx.db.query_one(
                "SELECT COUNT(*) FROM questions WHERE page_id=?", (page.page_id,))[0] > cap:
            # A recovered old job must not trim legacy data that predates this cap.
            return StageOutcome("existing page kept: legacy document exceeds question limit", Usage())
        remaining = max(0, cap - other_count)
        pending = self.ctx.db.query_one(
            "SELECT COUNT(*) FROM pages WHERE document_id=? AND status<>?",
            (page.document_id, DONE))[0]
        page_budget = math.ceil(remaining / max(1, pending))
        if not page_budget:
            if self.ctx.jobs.status(job.job_id) != "running":
                return StageOutcome("cancelled before write", Usage())
            if page.status == DONE:
                return StageOutcome("existing page kept: document question limit reached", Usage())
            with self.ctx.db.tx() as con:
                self.ctx.questions.replace_for_page(page.page_id, [], con)
                self.ctx.pages.set_content(page.page_id, "question_limit_reached",
                                           "Document question limit reached", con)
                self.ctx.pages.set_status(page.page_id, DONE, con=con)
            return StageOutcome("no questions: document question limit reached", Usage())
        # A queued job may have been created before a prompt edit and app restart.
        if job.prompt_version != P.PROMPT_VERSION:
            self.ctx.jobs.update(job.job_id, prompt_version=P.PROMPT_VERSION)
            job.prompt_version = P.PROMPT_VERSION
        path = self.ctx.abs_path(page.image_path)
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        try:
            res = provider.generate_json(job.model, P.page_prompt(page_budget, cap),
                                         [ImagePart(path.read_bytes(), mime)], P.PAGE_SCHEMA,
                                         self.ctx.settings.gemini_temperature, cancelled)
        except ResponseBlocked as e:
            # Retrying cannot help, and a document must still be able to finish.
            with self.ctx.db.tx() as con:
                self.ctx.questions.replace_for_page(page.page_id, [], con)
                self.ctx.pages.set_content(page.page_id, "blocked", str(e)[:300], con)
                self.ctx.pages.set_status(page.page_id, DONE, con=con)
            return StageOutcome("no questions: blocked by Gemini", Usage())
        items = require_list(res.data, "questions")
        page_type = as_str(res.data.get("page_type")).strip().lower()
        page_type = page_type if page_type in P.PAGE_TYPES else ""
        note = normalize_answer(as_str(res.data.get("page_note")))[:300]
        if page_type in P.NO_QUESTION_TYPES:
            # Enforced here, not just in the prompt: e.g. abstention questions are trivial to
            # invent for a blank or stamp-only page, and worthless.
            items = []
        questions = []
        abstentions = 0
        for item in items:
            if len(questions) >= page_budget:
                break
            n = len(questions) + 1
            q = build_question(item, f"{page.page_id}_q{n}", self.ctx.settings.abstain_distractor_ratio)
            if q is None:
                continue
            if q.question_type == TYPE_ABSTENTION:
                abstentions += 1
                if abstentions > 1:  # at most one abstention question per page
                    continue
            q.document_id, q.page_id, q.question_number = page.document_id, page.page_id, n
            q.model, q.prompt_version = job.model, job.prompt_version
            questions.append(q)
        if self.ctx.jobs.status(job.job_id) != "running":
            return StageOutcome("cancelled before write", res.usage, res.raw_text)
        with self.ctx.db.tx() as con:
            # Check again under the write lock, including edits from another app instance.
            other_count = con.execute(
                "SELECT COUNT(*) FROM questions WHERE document_id=? AND page_id<>?",
                (page.document_id, page.page_id)).fetchone()[0]
            questions = questions[:max(0, cap - other_count)]
            self.ctx.questions.replace_for_page(page.page_id, questions, con)
            self.ctx.pages.set_content(page.page_id, page_type, note, con)
            self.ctx.pages.set_status(page.page_id, DONE, con=con)
        dropped = len(items) - len(questions)
        summary = f"{len(questions)} question(s)" + (f", {dropped} item(s) dropped" if dropped else "")
        if page_type in P.NO_QUESTION_TYPES:
            summary = f"no questions: {page_type}"
        return StageOutcome(summary, res.usage, res.raw_text)

    def mark_failed(self, job: Job, error: str) -> None:
        self.ctx.pages.set_status(job.page_id, FAILED, error[:500])

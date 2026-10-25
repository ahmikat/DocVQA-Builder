from datetime import datetime, timedelta, timezone

import pytest

from bndocvqa.models.records import DONE, Question
from bndocvqa.services.gemini.parsing import ResponseParseError, extract_json
from bndocvqa.services.gemini.provider import PermanentError, TransientError
from bndocvqa.services.gemini.ratelimit import QuotaExhausted
from bndocvqa.services.library import LibraryService
from bndocvqa.services.pipeline import Pipeline
from conftest import ITEMS, FakeProvider, run


def test_one_request_per_page_and_questions_stored(ctx, doc):
    fake = FakeProvider([{"questions": ITEMS}, {"questions": ITEMS[:1]}])
    assert len(Pipeline(ctx).process_document("doc_1")) == 2
    run(ctx, fake)
    assert len(fake.calls) == 2 and all(c["images"] == 1 for c in fake.calls)
    assert "AT MOST 4 questions for this page" in fake.calls[0]["prompt"]
    assert "hard maximum of 8 questions" in fake.calls[0]["prompt"]
    qs = ctx.questions.for_document("doc_1")
    assert [q.question_id for q in qs] == ["doc_1_p1_q1", "doc_1_p1_q2", "doc_1_p1_q3", "doc_1_p2_q1"]
    assert all(p.status == "done" for p in ctx.pages.for_document("doc_1"))
    assert ctx.documents.is_finished("doc_1")
    assert qs[0].model == ctx.settings.gemini_model and qs[0].prompt_version == "page-v4-reasoning"


def test_malformed_items_dropped_not_stored(ctx, doc):
    bad = {**ITEMS[0], "distractors": ["ক"]}
    run_pages(ctx, [{"questions": [bad, ITEMS[0]]}, {"questions": []}])
    assert [q.question_id for q in ctx.questions.for_document("doc_1")] == ["doc_1_p1_q1"]


def run_pages(ctx, responses):
    Pipeline(ctx).process_document("doc_1")
    run(ctx, FakeProvider(responses))


def test_empty_page_is_done_with_no_questions(ctx, doc):
    run_pages(ctx, [{"questions": []}, {"questions": []}])
    assert ctx.documents.is_finished("doc_1") and ctx.questions.for_document("doc_1") == []


def test_finished_documents_are_not_reprocessed(ctx, doc):
    run_pages(ctx, [{"questions": ITEMS}, {"questions": ITEMS}])
    assert Pipeline(ctx).process_document("doc_1") == []


def test_transient_errors_retried(ctx, doc):
    run_pages(ctx, [TransientError("503"), ResponseParseError("bad"), {"questions": ITEMS}, {"questions": []}])
    assert ctx.documents.is_finished("doc_1")


def test_failed_page_marked_and_retried_by_processing_again(ctx, doc):
    run_pages(ctx, [PermanentError("400"), {"questions": []}])
    st = {p.page_number: p.status for p in ctx.pages.for_document("doc_1")}
    assert sorted(st.values()) == ["done", "failed"] and not ctx.documents.is_finished("doc_1")
    jobs = Pipeline(ctx).process_document("doc_1")
    assert len(jobs) == 1  # only the failed page
    run(ctx, FakeProvider([{"questions": ITEMS}]))
    assert ctx.documents.is_finished("doc_1")


def test_retrying_a_page_replaces_its_questions(ctx, doc):
    run_pages(ctx, [{"questions": ITEMS}, {"questions": []}])
    job = ctx.jobs.list()[0]
    ctx.jobs.update(job.job_id, status="running")  # crash after the write, before marking done
    ctx.jobs.recover_interrupted()
    run(ctx, FakeProvider([{"questions": ITEMS[:1]}]))
    assert len([q for q in ctx.questions.for_document("doc_1") if q.page_id == job.page_id]) == 1


def test_recovered_job_keeps_saved_question(ctx, doc):
    run_pages(ctx, [{"questions": ITEMS[:1]}, {"questions": []}])
    saved = ctx.questions.for_document("doc_1")[0]
    ctx.questions.save_edit(saved)
    job = ctx.jobs.list()[0]
    ctx.jobs.update(job.job_id, status="running")
    ctx.jobs.recover_interrupted()
    fake = FakeProvider([])
    run(ctx, fake)
    assert fake.calls == []
    assert ctx.questions.get(saved.question_id).reviewed


def test_daily_quota_parks_pages(ctx, doc):
    reset = datetime.now(timezone.utc) + timedelta(hours=5)
    run_pages(ctx, [QuotaExhausted("m", reset), QuotaExhausted("m", reset)])
    jobs = ctx.jobs.list()
    assert all(j.status == "queued" and j.attempts == 0 and "daily quota" in j.error for j in jobs)
    assert all(p.status == "pending" for p in ctx.pages.for_document("doc_1"))


def test_removing_a_document_cancels_its_work(ctx, doc):
    Pipeline(ctx).process_document("doc_1")
    LibraryService(ctx).remove_document("doc_1")
    assert ctx.jobs.list(statuses=("queued",)) == []


def test_errors_are_redacted(ctx, doc):
    key = ctx.settings.gemini_keys[0].api_key
    run_pages(ctx, [PermanentError(f"key {key} rejected"), {"questions": []}])
    assert all(key not in j.error for j in ctx.jobs.list())
    assert all(key not in p.error for p in ctx.pages.for_document("doc_1"))


def test_parse_fenced_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here: {"a": [1]} done') == {"a": [1]}
    for bad in ("no json", '{"a": [1}', ""):
        with pytest.raises(ResponseParseError):
            extract_json(bad)


@pytest.mark.parametrize("page_type", ["blank", "qr_or_barcode", "signature_or_stamp", "image_only", "unreadable"])
def test_no_content_pages_never_get_questions(ctx, doc, page_type):
    # Even if Gemini ignores the prompt and invents questions, none are stored.
    run_pages(ctx, [{"page_type": page_type, "page_note": "round seal and signature", "questions": ITEMS},
                    {"page_type": "text", "questions": ITEMS[:1]}])
    p1, p2 = ctx.pages.for_document("doc_1")
    assert (p1.content_type, p1.content_note, p1.status) == (page_type, "round seal and signature", "done")
    assert [q.page_id for q in ctx.questions.for_document("doc_1")] == ["doc_1_p2"]
    assert ctx.documents.is_finished("doc_1")


def test_at_most_one_abstention_per_page(ctx, doc):
    b03 = ITEMS[1]
    run_pages(ctx, [{"page_type": "text", "questions": [b03, {**b03, "question_bn": "অন্য ফি কত?"}, ITEMS[0]]},
                    {"page_type": "text", "questions": []}])
    types = [q.question_type for q in ctx.questions.for_document("doc_1")]
    assert types.count("abstention") == 1 and types.count("answerable") == 1


def test_missing_or_unknown_page_type_keeps_questions(ctx, doc):
    run_pages(ctx, [{"page_type": "weird", "questions": ITEMS[:1]}, {"questions": ITEMS[:1]}])
    assert len(ctx.questions.for_document("doc_1")) == 2
    assert [p.content_type for p in ctx.pages.for_document("doc_1")] == ["", ""]


def test_prompt_forbids_questions_on_empty_pages():
    from bndocvqa.models.taxonomy import AXIS_CODES
    from bndocvqa.prompts import AXIS_CHALLENGE_HINTS
    from bndocvqa.prompts import NO_QUESTION_TYPES, PAGE_SCHEMA, page_prompt
    t = page_prompt(5)
    assert '"questions": []' in t and "QR code" in t and "at most ONE per page" in t
    assert set(NO_QUESTION_TYPES) <= set(PAGE_SCHEMA["properties"]["page_type"]["enum"])
    assert set(AXIS_CHALLENGE_HINTS) == set(AXIS_CODES)
    assert all(t.count(f"`{code}`") == 1 for code in AXIS_CODES)
    assert "not templates or quotas" in t
    assert "exactly one clear, defensible answer" in " ".join(t.split())
    assert "knowledge outside the image" in t


@pytest.mark.parametrize("pages,maximum", [(0, 0), (1, 5), (2, 8), (3, 10),
                                              (4, 12), (5, 15), (6, 20), (20, 20)])
def test_document_question_limit_mapping(pages, maximum):
    from bndocvqa.services.question_limits import max_questions_for_document

    assert max_questions_for_document(pages) == maximum


def test_gemini_excess_is_trimmed_to_document_limit(ctx, doc):
    many = [ITEMS[0]] * 12
    fake = FakeProvider([{"page_type": "text", "questions": many}] * 2)
    Pipeline(ctx).process_document("doc_1")
    run(ctx, fake)
    assert len(ctx.questions.for_document("doc_1")) == 8
    assert all("AT MOST 4 questions for this page" in c["prompt"] for c in fake.calls)
    assert [len([q for q in ctx.questions.for_document("doc_1") if q.page_id == p.page_id])
            for p in ctx.pages.for_document("doc_1")] == [4, 4]


def test_unused_budget_moves_to_later_page(ctx, doc):
    fake = FakeProvider([{"page_type": "blank", "questions": ITEMS},
                         {"page_type": "text", "questions": [ITEMS[0]] * 12}])
    Pipeline(ctx).process_document("doc_1")
    run(ctx, fake)
    assert len(ctx.questions.for_document("doc_1")) == 8
    assert "AT MOST 8 questions for this page" in fake.calls[1]["prompt"]


def test_no_gemini_call_after_limit_reached(ctx, doc):
    fake = FakeProvider([])
    # Simulate a pre-existing count from an earlier, less strict version.
    with ctx.db.tx() as con:
        for n in range(8):
            q = Question(
                question_id=f"legacy_{n}", document_id="doc_1", page_id="doc_1_p1",
                question_number=n + 1)
            ctx.questions._insert(con, q)
        ctx.pages.set_status("doc_1_p1", DONE, con=con)
    Pipeline(ctx).process_document("doc_1")
    run(ctx, fake)
    assert fake.calls == []
    assert len(ctx.questions.for_document("doc_1")) == 8
    assert ctx.pages.get("doc_1_p2").content_type == "question_limit_reached"
    assert all(j.status == "succeeded" for j in ctx.jobs.list())


def test_legacy_over_limit_page_is_preserved_on_recovered_job(ctx, doc):
    with ctx.db.tx() as con:
        for n in range(9):
            ctx.questions._insert(con, Question(
                question_id=f"legacy_{n}", document_id="doc_1", page_id="doc_1_p1",
                question_number=n + 1))
        ctx.pages.set_status("doc_1_p1", DONE, con=con)
    Pipeline(ctx).enqueue_page("doc_1_p1")
    fake = FakeProvider([])
    run(ctx, fake)
    assert fake.calls == []
    assert len(ctx.questions.for_document("doc_1")) == 9


def test_only_one_page_per_document_is_claimed_at_a_time(ctx, doc):
    from bndocvqa.database.connection import utcnow

    Pipeline(ctx).process_document("doc_1")
    first = ctx.jobs.claim_next(utcnow())
    assert first is not None
    assert ctx.jobs.claim_next(utcnow()) is None
    ctx.jobs.update(first.job_id, status="succeeded")
    second = ctx.jobs.claim_next(utcnow())
    assert second is not None and second.page_id != first.page_id


def test_safety_blocked_page_finishes_without_questions(ctx, doc):
    from bndocvqa.services.gemini.provider import ResponseBlocked
    run_pages(ctx, [ResponseBlocked("response blocked: SAFETY"), {"page_type": "text", "questions": ITEMS[:1]}])
    p1 = ctx.pages.for_document("doc_1")[0]
    assert (p1.status, p1.content_type) == ("done", "blocked") and ctx.documents.is_finished("doc_1")

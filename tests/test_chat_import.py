"""A chat question must keep its document, every evidence page, and its review gate."""
import json
import os

import pytest

from bndocvqa.services.chat_import import prepare_chat_import, stage_chat_import
from bndocvqa.services.pipeline import Pipeline


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def no_dialogs(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    for name in ("question", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *args, **kwargs: QMessageBox.Yes))


def payload(document_id="doc_1"):
    return {"schema_version": "gemini_chat_multipage_v1", "document_id": document_id,
            "questions": [{
                "question_bn": "দুই পৃষ্ঠার মান যোগ করলে কত?",
                "source_pages": [
                    {"page_id": f"{document_id}_p1", "evidence_snippet": "প্রথম মান ১০", "used_for": "প্রথম যোগফল"},
                    {"page_id": f"{document_id}_p2", "evidence_snippet": "দ্বিতীয় মান ২০", "used_for": "দ্বিতীয় যোগফল"},
                ],
                "question_format": "mcq5", "question_type": "answerable", "primary_axis": "C08",
                "sub_axes": ["C13"],
                "options": {"A": "১০", "B": "২০", "C": "৩০", "D": "৪০", "E": "৫০"},
                "correct_option": "C", "answer_bn": "৩০",
                "reasoning_steps": ["১০ + ২০ = ৩০"], "rationale": "দুই পৃষ্ঠার তথ্য যোগ করার পরীক্ষা",
            }]}


def test_stage_review_export_and_duplicate(ctx, doc):
    batch = prepare_chat_import(ctx, json.dumps(payload(), ensure_ascii=False))
    assert batch.document_id == doc.document_id and batch.existing == 0
    ids = stage_chat_import(ctx, batch)
    assert len(ids) == 1
    q = ctx.questions.get(ids[0])
    assert not q.reviewed
    assert [s.page_id for s in q.source_pages] == ["doc_1_p1", "doc_1_p2"]
    assert q.reasoning_steps == ["১০ + ২০ = ৩০"]
    ctx.portable.sync()
    assert not (ctx.data_dir / "questions.jsonl").read_text(encoding="utf-8").strip()
    assert prepare_chat_import(ctx, json.dumps(payload(), ensure_ascii=False)).existing == 1
    assert stage_chat_import(ctx, batch) == []
    queued = Pipeline(ctx).process_document("doc_1")
    assert [job.page_id for job in queued] == ["doc_1_p2"]  # imports cannot be replaced by page generation

    q.reasoning_steps.append("ফলটি option C-তে আছে")
    ctx.questions.save_edit(q)
    ctx.portable.sync()
    record = json.loads((ctx.data_dir / "questions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert [p["page_id"] for p in record["source_pages"]] == ["doc_1_p1", "doc_1_p2"]
    assert record["reasoning_steps"][-1] == "ফলটি option C-তে আছে"
    assert record["answer_bn"] == record["options"][record["correct_option"]]


def test_archive_restores_multi_page_evidence(ctx, doc, tmp_path):
    from bndocvqa.services.context import open_context
    from bndocvqa.services.portable import export_workspace_archive

    ids = stage_chat_import(ctx, prepare_chat_import(ctx, json.dumps(payload(), ensure_ascii=False)))
    ctx.questions.save_edit(ctx.questions.get(ids[0]))
    archive = export_workspace_archive(ctx, tmp_path / "archive")
    restored = open_context(data_dir=archive.folder, log=False)
    try:
        q = restored.questions.get(ids[0])
        assert q.reviewed and len(q.source_pages) == 2
        assert q.source_pages[1].used_for == "দ্বিতীয় যোগফল"
        assert q.reasoning_steps == ["১০ + ২০ = ৩০"]
    finally:
        restored.db.close()


def test_rejects_wrong_document_page_and_incomplete_json(ctx, doc):
    wrong = payload("doc_99")
    with pytest.raises(ValueError, match="not in this workspace"):
        prepare_chat_import(ctx, json.dumps(wrong, ensure_ascii=False))
    wrong = payload()
    wrong["questions"][0]["source_pages"][1]["page_id"] = "doc_1_p99"
    with pytest.raises(ValueError, match="not in doc_1"):
        prepare_chat_import(ctx, json.dumps(wrong, ensure_ascii=False))
    with pytest.raises(ValueError, match="incomplete JSON"):
        prepare_chat_import(ctx, '{"schema_version": "gemini_chat_multipage_v1",')
    assert ctx.db.query_one("SELECT COUNT(*) FROM questions")[0] == 0


def test_review_ui_navigates_source_pages(qapp, ctx, doc, no_dialogs):
    from bndocvqa.ui.main_window import MainWindow

    ids = stage_chat_import(ctx, prepare_chat_import(ctx, json.dumps(payload(), ensure_ascii=False)))
    window = MainWindow(ctx)
    window._open_imported("doc_1", ids[0])
    assert window.view.q.question_id == ids[0]
    assert window.view.source_list.count() == 2
    window.view.source_list.setCurrentRow(1)
    assert window.view.viewer.current_page.page_id == "doc_1_p2"
    window.view.source_used_for.setText("যোগফলের দ্বিতীয় অংশ")
    window.view.save()
    assert ctx.questions.get(ids[0]).source_pages[1].used_for == "যোগফলের দ্বিতীয় অংশ"
    assert ctx.questions.get(ids[0]).reviewed
    window.close()


def test_paste_dialog_previews_match_and_opens_view(qapp, ctx, doc, no_dialogs):
    from bndocvqa.ui.chat_import_dialog import ChatImportDialog
    from bndocvqa.ui.main_window import MainWindow

    window = MainWindow(ctx)
    dialog = ChatImportDialog(ctx, window)
    dialog.input.setPlainText(json.dumps(payload(), ensure_ascii=False))
    dialog.preview()
    assert "doc_1" in dialog.summary.toPlainText()
    assert doc.original_filename in dialog.summary.toPlainText()
    assert dialog.stage_btn.isEnabled()
    dialog.stage()
    window._open_imported(dialog.document_id, dialog.created_ids[0])
    assert window.view.q.question_id == dialog.created_ids[0]
    assert not window.view.q.reviewed
    window.close()


def test_compact_review_order_and_full_question_height(qapp, ctx, doc, no_dialogs):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QGroupBox
    from bndocvqa.ui.main_window import MainWindow

    ids = stage_chat_import(ctx, prepare_chat_import(ctx, json.dumps(payload(), ensure_ascii=False)))
    window = MainWindow(ctx)
    window.resize(1500, 920)
    window.show()
    window._open_imported("doc_1", ids[0])
    qapp.processEvents()
    view = window.view
    options = view.findChild(QGroupBox, "reviewOptions")
    top = lambda widget: widget.mapTo(view, QPoint(0, 0)).y()
    assert top(view.question_edit) < top(options) < top(view.reasoning) < top(view.source_list)
    assert top(view.rationale) < top(view.axis_combo) < top(view.sub_axes)
    short_height = view.question_edit.height()
    view.question_edit.setPlainText("দীর্ঘ প্রশ্নের লেখা " * 35)
    qapp.processEvents()
    assert view.question_edit.height() > short_height
    assert view.question_edit.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff

    view.reasoning.setPlainText("প্রথম ধাপের ব্যাখ্যা এবং হিসাব। " * 35)
    qapp.processEvents()
    full_height = view.reasoning.height()
    assert full_height > 62
    assert view.reasoning.verticalScrollBar().maximum() == 0
    grip = view.reasoning_grip
    QTest.mousePress(grip, Qt.LeftButton, pos=QPoint(20, 5))
    QTest.mouseMove(grip, QPoint(20, -full_height))
    QTest.mouseRelease(grip, Qt.LeftButton, pos=QPoint(20, -full_height))
    qapp.processEvents()
    assert view.reasoning.height() == 36
    assert view.reasoning.verticalScrollBar().maximum() > 0
    reloaded = ctx.questions.get(ids[0])
    reloaded.reasoning_steps = ["প্রথম ধাপের ব্যাখ্যা এবং হিসাব। " * 35]
    view._fill(reloaded)
    qapp.processEvents()
    assert view.reasoning.height() == 36  # manual size survives a question reload
    QTest.mouseDClick(grip, Qt.LeftButton, pos=QPoint(20, 5))
    qapp.processEvents()
    assert view.reasoning.height() >= full_height
    assert view.reasoning.verticalScrollBar().maximum() == 0
    window.close()

"""Offscreen smoke tests for the two-tab UI and the CLI."""
import os
import json
from pathlib import Path

import pytest

from bndocvqa.cli import main
from bndocvqa.services.library import LibraryService
from bndocvqa.services.pipeline import Pipeline
from conftest import ITEMS, FakeProvider, make_pdf, run


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def no_dialogs(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    for name in ("question", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: shown.append(a[1:3]) or QMessageBox.Yes))
    return shown


def test_window_has_only_library_and_view(qapp, ctx, doc, no_dialogs):
    from bndocvqa.ui.main_window import MainWindow
    from PySide6.QtWidgets import QPushButton
    w = MainWindow(ctx)
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Library", "View"]
    assert not w.menuBar().actions()
    actions = {button.text() for button in w.library.findChildren(QPushButton)}
    assert {"View", "Review questions", "Export ZIP…"} <= actions
    w.close()


def test_view_opens_saved_html_and_review_opens_editor(qapp, ctx, doc, monkeypatch):
    from bndocvqa.ui import library_view
    from bndocvqa.ui.main_window import MainWindow
    from PySide6.QtWidgets import QPushButton

    opened = []
    monkeypatch.setattr(library_view, "_open_local_html", lambda path: opened.append(path) or True)
    w = MainWindow(ctx)
    buttons = {button.text(): button for button in w.library.findChildren(QPushButton)}
    buttons["View"].click()
    assert opened == [ctx.data_dir / "index.html"]
    assert opened[0].is_file()
    w.library._set_all(True)
    buttons["Review questions"].click()
    assert w.tabs.currentWidget() is w.view and w.view.document_id == doc.document_id
    w.close()


def test_windows_html_opener_uses_default_file_application(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows file association")
    from bndocvqa.ui.library_view import _open_local_html

    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path))
    path = tmp_path / "index.html"
    path.write_text("<html></html>", encoding="utf-8")
    assert _open_local_html(path)
    assert opened == [str(path)]


def test_process_needs_ticked_rows(qapp, ctx, doc, no_dialogs):
    from bndocvqa.ui.main_window import MainWindow
    w = MainWindow(ctx)
    requested = []
    w.library.processRequested.connect(requested.append)
    w.library._process()
    assert requested == [] and no_dialogs  # nothing ticked -> message, no processing
    w.library._set_all(True)
    w.library._process()
    assert requested == [["doc_1"]]
    w.close()


def test_view_edit_and_axis_filter(qapp, ctx, doc, no_dialogs):
    Pipeline(ctx).process_document("doc_1")
    run(ctx, FakeProvider([{"questions": ITEMS}, {"questions": ITEMS[:1]}]))
    from bndocvqa.ui.main_window import MainWindow
    w = MainWindow(ctx)
    w._open_document("doc_1")
    v = w.view
    labels = [v.axis_filter.itemText(i) for i in range(v.axis_filter.count())]
    assert labels[0] == "All (4)" and any(t.startswith("B01") and t.endswith("(2)") for t in labels)
    v.axis_filter.setCurrentIndex(v.axis_filter.findData("B04"))
    assert v.qlist.count() == 1
    v.axis_filter.setCurrentIndex(0)
    v.qlist.setCurrentRow(0)
    qid = v.q.question_id
    v.question_edit.setPlainText("সম্পাদিত প্রশ্ন?")
    v.save()
    got = ctx.questions.get(qid)
    assert got.question_bn == "সম্পাদিত প্রশ্ন?" and got.edited and got.reviewed
    assert w.library.table.item(0, 5).text() == "1/4"
    assert [r["question_id"] for r in json.loads((ctx.data_dir / "questions.json").read_text(encoding="utf-8"))] == [qid]
    assert ctx.db.query_one("SELECT COUNT(*) FROM question_history WHERE question_id=?", (qid,))[0] == 1
    w.close()


def test_status_text(qapp, ctx, doc, no_dialogs):
    from bndocvqa.ui.library_view import LibraryView
    lib = LibraryView(ctx)
    assert lib.table.horizontalHeaderItem(6).text() == "Gemini Generated"
    assert lib.table.item(0, 6).text() == "Unfinished"
    Pipeline(ctx).process_document("doc_1")
    lib.refresh()
    assert lib.table.item(0, 6).text().startswith("Unfinished")
    run(ctx, FakeProvider([{"questions": ITEMS}, {"questions": []}]))
    lib.refresh()
    assert lib.table.item(0, 6).text() == "Finished"
    assert lib.table.item(0, 5).text() == "0/3"


def test_library_search_and_summary_cards(qapp, ctx, doc, tmp_path):
    from bndocvqa.ui.library_view import LibraryView

    LibraryService(ctx).import_file(make_pdf(tmp_path / "other.pdf", 1, "other"))
    lib = LibraryView(ctx)
    assert lib.metric_values["documents"].text() == "2"
    lib.search.setText("other.pdf")
    assert lib.table.isRowHidden(0) and not lib.table.isRowHidden(1)
    lib.search.clear()
    assert not lib.table.isRowHidden(0) and not lib.table.isRowHidden(1)


def test_cli_import_list_export(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    assert main(["--data-dir", ws, "import", str(make_pdf(tmp_path / "a.pdf", 1, "cli"))]) == 0
    assert '"doc_1"' in capsys.readouterr().out
    assert main(["--data-dir", ws, "list"]) == 0
    capsys.readouterr()
    assert main(["--data-dir", ws, "export", str(tmp_path / "out")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["documents"] == 1 and result["pages"] == 1 and result["questions"] == 0
    assert Path(result["zip"]).is_file()

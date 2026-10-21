"""Offscreen smoke tests for the two-tab UI and the CLI."""
import os

import pytest

from bndocvqa.cli import main
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
    w = MainWindow(ctx)
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Library", "View"]
    assert not w.menuBar().actions()
    w.close()


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
    assert got.question_bn == "সম্পাদিত প্রশ্ন?" and got.edited
    assert ctx.db.query_one("SELECT COUNT(*) FROM question_history WHERE question_id=?", (qid,))[0] == 1
    w.close()


def test_status_text(qapp, ctx, doc, no_dialogs):
    from bndocvqa.ui.library_view import LibraryView
    lib = LibraryView(ctx)
    assert lib.table.item(0, 5).text() == "Not processed"
    Pipeline(ctx).process_document("doc_1")
    lib.refresh()
    assert lib.table.item(0, 5).text().startswith("⏳ Processing")
    run(ctx, FakeProvider([{"questions": ITEMS}, {"questions": []}]))
    lib.refresh()
    assert lib.table.item(0, 5).text() == "✔ Finished"


def test_cli_import_list_export(tmp_path, capsys):
    ws = str(tmp_path / "ws")
    assert main(["--data-dir", ws, "import", str(make_pdf(tmp_path / "a.pdf", 1, "cli"))]) == 0
    assert '"doc_1"' in capsys.readouterr().out
    assert main(["--data-dir", ws, "list"]) == 0
    assert main(["--data-dir", ws, "export", str(tmp_path / "out")]) == 2  # nothing finished yet

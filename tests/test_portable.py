import csv
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from bndocvqa.config import Settings
from bndocvqa.services.context import open_context
from bndocvqa.services.files import sha256_file
from bndocvqa.services.gemini.usage import RequestLog
from bndocvqa.services.pipeline import Pipeline
from bndocvqa.services.portable import export_workspace_archive
from conftest import ITEMS, FakeProvider, run


def _html_data(html: str) -> dict:
    payload = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
    return json.loads(payload)


def _html_questions(html: str) -> list[dict]:
    return _html_data(html)["questions"]


def test_all_tables_mirrored_and_html_tracks_edits(ctx, doc):
    Pipeline(ctx).process_document(doc.document_id)
    run(ctx, FakeProvider([{"page_type": "text", "questions": ITEMS},
                           {"page_type": "blank", "questions": []}]))
    question = ctx.questions.for_document(doc.document_id)[0]
    question.question_bn = "সংশোধিত প্রশ্ন?"
    ctx.questions.save_edit(question)
    RequestLog(ctx.db).record("project", "model", datetime.now(timezone.utc))
    ctx.portable.sync()

    state = json.loads((ctx.data_dir / "data/state.json").read_text(encoding="utf-8"))
    assert state["format_version"] == 1
    for table, rows in state["tables"].items():
        assert len(rows) == len(ctx.db.query(f'SELECT * FROM "{table}"'))
        assert json.loads((ctx.data_dir / f"data/{table}.json").read_text(encoding="utf-8")) == rows
        with open(ctx.data_dir / f"data/{table}.csv", encoding="utf-8-sig", newline="") as f:
            assert len(list(csv.DictReader(f))) == len(rows)
    assert state["tables"]["question_history"]
    assert len(state["tables"]["api_requests"]) == 1
    assert (ctx.data_dir / "documents/doc_1.pdf").is_file()
    assert (ctx.data_dir / "images/doc_1_p1.png").is_file()
    html = (ctx.data_dir / "index.html").read_text(encoding="utf-8")
    assert "সংশোধিত প্রশ্ন?" in html and "Search documents" in html
    assert "No saved questions" in html and "images/doc_1_p1.png" in html
    assert [q["question_bn"] for q in _html_questions(html)] == ["সংশোধিত প্রশ্ন?"]


def test_only_manually_saved_questions_enter_dataset_files(ctx, doc, tmp_path):
    Pipeline(ctx).process_document(doc.document_id)
    run(ctx, FakeProvider([{"page_type": "text", "questions": ITEMS},
                           {"page_type": "text", "questions": ITEMS[:1]}]))
    ctx.portable.sync()
    assert json.loads((ctx.data_dir / "questions.json").read_text(encoding="utf-8")) == []
    assert len(json.loads((ctx.data_dir / "data/questions.json").read_text(encoding="utf-8"))) == 4
    q = ctx.questions.for_document(doc.document_id)[0]
    saved = ctx.questions.save_edit(q)  # no text edit: Save still accepts it
    assert saved.reviewed and not saved.edited and saved.reviewed_at
    assert ctx.questions.reviewed_counts_by_document() == {doc.document_id: 1}
    ctx.portable.sync()
    records = json.loads((ctx.data_dir / "questions.json").read_text(encoding="utf-8"))
    assert [r["question_id"] for r in records] == [q.question_id]
    assert records[0]["reviewed"] is True
    assert len((ctx.data_dir / "questions.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    with open(ctx.data_dir / "questions.csv", encoding="utf-8-sig", newline="") as f:
        assert [row["question_id"] for row in csv.DictReader(f)] == [q.question_id]
    html = (ctx.data_dir / "index.html").read_text(encoding="utf-8")
    assert [record["question_id"] for record in _html_questions(html)] == [q.question_id]
    assert ITEMS[1]["question_bn"] not in html
    assert len(_html_data(html)["pages"]) == 2
    assert _html_data(html)["documents"][doc.document_id] == "documents/doc_1.pdf"
    archive = export_workspace_archive(ctx, tmp_path / "out")
    assert archive.questions == 1
    assert len(json.loads((archive.folder / "questions.json").read_text(encoding="utf-8"))) == 1
    assert [record["question_id"] for record in _html_questions(
        (archive.folder / "index.html").read_text(encoding="utf-8"))] == [q.question_id]
    with zipfile.ZipFile(archive.path) as zf:
        assert len(json.loads(zf.read(f"{archive.folder.name}/questions.json"))) == 1


def test_archive_includes_unfinished_data_media_and_valid_zip(ctx, doc, tmp_path):
    result = export_workspace_archive(ctx, tmp_path / "out")
    assert (result.documents, result.pages, result.questions) == (1, 2, 0)
    assert result.path.is_file() and result.folder.is_dir()
    assert (result.folder / "documents/doc_1.pdf").is_file()
    assert (result.folder / "images/doc_1_p2.png").is_file()
    assert (result.folder / "data/state.json").is_file()
    assert (result.folder / "data/jobs.csv").is_file()
    assert (result.folder / "questions.json").is_file()
    assert (result.folder / "questions.xlsx").is_file()
    assert "Not processed yet" in (result.folder / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["table_counts"]["pages"] == 2 and manifest["api_keys_included"] is False
    for file in manifest["files"]:
        assert sha256_file(result.folder / file["path"]) == file["sha256"]
    with zipfile.ZipFile(result.path) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert f"{result.folder.name}/index.html" in names
        assert f"{result.folder.name}/data/state.json" in names
        assert f"{result.folder.name}/questions.xlsx" in names
        assert f"{result.folder.name}/documents/doc_1.pdf" in names
        assert not any(name.endswith(".sqlite") or "keys.json" in name for name in names)


def test_json_snapshot_restores_a_new_workspace(ctx, doc, tmp_path):
    Pipeline(ctx).process_document(doc.document_id)
    run(ctx, FakeProvider([{"page_type": "text", "questions": ITEMS}, {"questions": []}]))
    saved_id = ctx.questions.for_document("doc_1")[0].question_id
    ctx.questions.save_edit(ctx.questions.get(saved_id))
    RequestLog(ctx.db).record("project", "model", datetime.now(timezone.utc))
    ctx.portable.sync()
    restored_dir = tmp_path / "restored"
    restored_dir.mkdir()
    for folder in ("data", "documents", "images"):
        shutil.copytree(ctx.data_dir / folder, restored_dir / folder)
    restored = open_context(settings=Settings(data_dir=restored_dir, render_dpi=50), log=False)
    try:
        assert restored.documents.get("doc_1").file_hash == doc.file_hash
        assert len(restored.pages.for_document("doc_1")) == 2
        assert len(restored.questions.for_document("doc_1")) == len(ctx.questions.for_document("doc_1"))
        assert restored.questions.get(saved_id).reviewed
        assert len(json.loads((restored_dir / "questions.json").read_text(encoding="utf-8"))) == 1
        assert len(restored.db.query("SELECT * FROM api_requests")) == 1
        assert (restored_dir / "bndocvqa.sqlite").is_file()
    finally:
        restored.db.close()


def test_old_snapshot_restores_previously_edited_questions_as_saved(ctx, doc, tmp_path):
    Pipeline(ctx).process_document(doc.document_id)
    run(ctx, FakeProvider([{"questions": ITEMS[:1]}, {"questions": []}]))
    question = ctx.questions.for_document("doc_1")[0]
    question.question_bn = "আগে সংশোধিত প্রশ্ন?"
    ctx.questions.save_edit(question)
    ctx.portable.sync()
    restored_dir = tmp_path / "old_snapshot"
    restored_dir.mkdir()
    for folder in ("data", "documents", "images"):
        shutil.copytree(ctx.data_dir / folder, restored_dir / folder)
    state_path = restored_dir / "data/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for row in state["tables"]["questions"]:
        row.pop("reviewed")
        row.pop("reviewed_at")
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    restored = open_context(settings=Settings(data_dir=restored_dir, render_dpi=50), log=False)
    try:
        assert restored.questions.get(question.question_id).reviewed
        assert len(json.loads((restored_dir / "questions.json").read_text(encoding="utf-8"))) == 1
    finally:
        restored.db.close()


def test_existing_sqlite_media_migrates_without_losing_old_copies(ctx, doc):
    old_docs, old_images = ctx.data_dir / "originals", ctx.data_dir / "pages"
    old_docs.mkdir()
    old_images.mkdir()
    original = ctx.data_dir / doc.file_path
    shutil.move(str(original), old_docs / original.name)
    for page in ctx.pages.for_document(doc.document_id):
        image = ctx.data_dir / page.image_path
        shutil.move(str(image), old_images / image.name)
    with ctx.db.tx() as con:
        con.execute("UPDATE documents SET file_path='originals/doc_1.pdf' WHERE document_id='doc_1'")
        con.execute("UPDATE pages SET image_path=REPLACE(image_path, 'images/', 'pages/')")
    reopened = open_context(settings=Settings(data_dir=ctx.data_dir, render_dpi=50), log=False)
    try:
        migrated = reopened.documents.get("doc_1")
        assert migrated.file_path == "documents/doc_1.pdf"
        assert sha256_file(reopened.abs_path(migrated.file_path)) == doc.file_hash
        assert (old_docs / "doc_1.pdf").is_file()
        assert all(p.image_path.startswith("images/") and reopened.abs_path(p.image_path).is_file()
                   for p in reopened.pages.for_document("doc_1"))
        assert len(json.loads((ctx.data_dir / "data/state.json").read_text(encoding="utf-8"))["tables"]["pages"]) == 2
    finally:
        reopened.db.close()

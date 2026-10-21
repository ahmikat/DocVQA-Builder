import os
import stat

from bndocvqa.database import open_database
from bndocvqa.services.files import sha256_file
from bndocvqa.services.library import LibraryService
from conftest import make_image, make_pdf


def test_migrations_idempotent(tmp_path):
    db = open_database(tmp_path / "x.sqlite")
    assert db.schema_version() >= 1 and db.migrate() == []


def test_auto_naming_increases_and_never_reuses(ctx, tmp_path):
    lib = LibraryService(ctx)
    names = [lib.import_file(make_pdf(tmp_path / f"f{i}.pdf", 1, str(i)))[0].document_id for i in range(3)]
    assert names == ["doc_1", "doc_2", "doc_3"]
    lib.remove_document("doc_3")
    assert lib.import_file(make_pdf(tmp_path / "f9.pdf", 1, "9"))[0].document_id == "doc_4"


def test_pages_rendered_with_stable_names(ctx, doc):
    pages = ctx.pages.for_document(doc.document_id)
    assert [p.page_id for p in pages] == ["doc_1_p1", "doc_1_p2"]
    assert [ctx.abs_path(p.image_path).name for p in pages] == ["doc_1_p1.png", "doc_1_p2.png"]
    assert all(p.status == "pending" and p.width > 0 for p in pages)
    assert doc.original_filename == "নোটিশ sample.pdf"


def test_original_preserved_read_only(ctx, doc):
    stored = ctx.abs_path(doc.file_path)
    assert stored.name == "doc_1.pdf" and sha256_file(stored) == doc.file_hash
    assert not os.stat(stored).st_mode & stat.S_IWRITE


def test_duplicates_skipped(ctx, doc, tmp_path):
    copy = tmp_path / "copy.pdf"
    copy.write_bytes(ctx.abs_path(doc.file_path).read_bytes())
    res = LibraryService(ctx).import_files([copy])
    assert not res.imported and res.duplicates[0][1].document_id == "doc_1"


def test_image_import_and_bad_files(ctx, tmp_path):
    bad = tmp_path / "x.docx"
    bad.write_text("hi")
    res = LibraryService(ctx).import_files([make_image(tmp_path / "scan.jpg"), bad])
    assert [d.page_count for d in res.imported] == [1] and len(res.failed) == 1


def test_remove_moves_files_to_trash(ctx, doc):
    stored = ctx.abs_path(doc.file_path)
    trash = LibraryService(ctx).remove_document("doc_1")
    assert ctx.documents.get("doc_1") is None and not stored.exists() and any(trash.rglob("*.pdf"))

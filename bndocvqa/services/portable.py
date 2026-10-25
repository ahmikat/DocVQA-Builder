"""Readable workspace mirrors and a complete, offline ZIP archive.

SQLite remains the transactional working database. Every committed table is
mirrored as JSON and CSV, and state.json can rebuild a missing working database.
API-key storage is deliberately outside this workspace and is never archived.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import stat
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models.taxonomy import AXIS_BY_CODE
from .files import resolve_inside, sha256_file
from .viewer_html import render_viewer

RESTORE_ORDER = ("meta", "documents", "pages", "questions", "question_options",
                 "question_sub_axes", "question_history", "jobs", "api_requests")
FORMAT_VERSION = 1
log = logging.getLogger(__name__)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _order(document_id: str) -> int:
    try:
        return int(document_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _read_tables(db) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """Read all application tables from one consistent SQLite snapshot."""
    con = db.con
    con.execute("BEGIN")
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables, columns = {}, {}
        for name in names:
            # Names come from SQLite's own schema, not user input.
            columns[name] = [r[1] for r in con.execute(f'PRAGMA table_info("{name}")')]
            tables[name] = [dict(r) for r in con.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
        con.execute("COMMIT")
        return tables, columns
    except BaseException:
        con.execute("ROLLBACK")
        raise


def _viewer_records(tables: dict[str, list[dict]]) -> tuple[list[dict], list[dict], dict[str, str]]:
    docs = {d["document_id"]: d for d in tables.get("documents", [])}
    pages = {p["page_id"]: p for p in tables.get("pages", [])}
    options: dict[str, dict[str, str]] = {}
    for option in tables.get("question_options", []):
        options.setdefault(option["question_id"], {})[option["label"]] = option["text"]
    sub_axes: dict[str, list[str]] = {}
    for sub in tables.get("question_sub_axes", []):
        sub_axes.setdefault(sub["question_id"], []).append(sub["axis_code"])
    records = []
    for q in tables.get("questions", []):
        doc, page = docs[q["document_id"]], pages[q["page_id"]]
        axis = AXIS_BY_CODE.get(q["primary_axis"])
        records.append({
            "question_id": q["question_id"], "document_id": q["document_id"],
            "document_path": f"documents/{Path(doc['file_path']).name}",
            "page_id": q["page_id"], "page_number": page["page_number"],
            "image_path": f"images/{Path(page['image_path']).name}",
            "question_bn": q["question_bn"], "question_format": q["question_format"],
            "question_type": q["question_type"], "options": options.get(q["question_id"], {}),
            "correct_option": q["correct_option"], "answer_bn": q["answer_bn"],
            "primary_axis": q["primary_axis"], "axis_name": axis.name if axis else q["primary_axis"],
            "sub_axes": sorted(sub_axes.get(q["question_id"], [])),
            "evidence_snippet": q["evidence_snippet"], "rationale": q["rationale"],
            "edited": bool(q["edited"]), "reviewed": bool(q["reviewed"]),
            "reviewed_at": q["reviewed_at"], "model": q["model"],
            "prompt_version": q["prompt_version"], "source_file": doc["original_filename"],
        })
    records.sort(key=lambda r: (_order(r["document_id"]), r["page_number"], r["question_id"]))
    page_rows = [{"page_id": p["page_id"], "document_id": p["document_id"],
                  "page_number": p["page_number"],
                  "image_path": f"images/{Path(p['image_path']).name}",
                  "content_type": p["content_type"], "content_note": p["content_note"],
                  "status": p["status"], "error": p["error"]}
                 for p in tables.get("pages", [])]
    page_rows.sort(key=lambda p: (_order(p["document_id"]), p["page_number"]))
    doc_paths = {d["document_id"]: f"documents/{Path(d['file_path']).name}" for d in docs.values()}
    return records, page_rows, doc_paths


class PortableStore:
    """Keep a human-readable copy of every committed application table."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.root = ctx.data_dir
        self.data = self.root / "data"
        self._lock = threading.RLock()
        self._timer_lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def schedule(self) -> None:
        """Coalesce bursts of job/status writes into one portable snapshot."""
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(0.5, self._background_sync)
            self._timer.daemon = True
            self._timer.start()

    def _background_sync(self) -> None:
        try:
            self.sync()
            self.ctx.db.last_mirror_error = ""
        except Exception as exc:
            self.ctx.db.last_mirror_error = str(exc)
            log.exception("portable data mirror failed")

    def sync(self) -> dict[str, int]:
        from .export import CSV_COLUMNS, _flat

        with self._lock, self.ctx.db._write_lock:
            with self._timer_lock:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
            tables, columns = _read_tables(self.ctx.db)
            generated_at = datetime.now(timezone.utc)
            state = {"format_version": FORMAT_VERSION,
                     "generated_at": generated_at.isoformat(timespec="seconds"), "tables": tables}
            for name, rows in tables.items():
                _atomic_bytes(self.data / f"{name}.json", _json_bytes(rows))
                _atomic_bytes(self.data / f"{name}.csv", _csv_bytes(columns[name], rows))
            _atomic_bytes(self.data / "state.json", _json_bytes(state))

            records, pages, doc_paths = _viewer_records(tables)
            saved_records = [r for r in records if r["reviewed"]]
            jsonl = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in saved_records)
            _atomic_bytes(self.root / "questions.json", _json_bytes(saved_records))
            _atomic_bytes(self.root / "questions.jsonl", jsonl.encode("utf-8"))
            _atomic_bytes(self.root / "questions.csv", _csv_bytes(CSV_COLUMNS, [_flat(r) for r in saved_records]))
            _atomic_bytes(self.root / "index.html",
                          render_viewer(saved_records, pages, generated_at, doc_paths,
                                        title="Bangla DocVQA Workspace", time_label="updated").encode("utf-8"))
            counts = {name: len(rows) for name, rows in tables.items()}
            _atomic_bytes(self.data / "manifest.json", _json_bytes({
                "format_version": FORMAT_VERSION, "generated_at": state["generated_at"],
                "table_counts": counts, "saved_questions": len(saved_records), "viewer": "../index.html",
                "questions_json": "../questions.json", "questions_jsonl": "../questions.jsonl",
                "questions_csv": "../questions.csv",
            }))
            self.ctx.db.last_mirror_error = ""
            return counts


def restore_state(db, data_dir: Path) -> None:
    """Recover a missing SQLite working database from the readable snapshot."""
    path = data_dir / "data" / "state.json"
    if not path.is_file():
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("format_version") != FORMAT_VERSION or not isinstance(state.get("tables"), dict):
        raise ValueError(f"unsupported portable state in {path}")
    tables = state["tables"]
    for d in tables.get("documents", []):
        if not resolve_inside(data_dir, d["file_path"]).is_file():
            raise FileNotFoundError(f"missing document needed to restore {d['document_id']}: {d['file_path']}")
    for p in tables.get("pages", []):
        if not resolve_inside(data_dir, p["image_path"]).is_file():
            raise FileNotFoundError(f"missing page image needed to restore {p['page_id']}: {p['image_path']}")
    with db.tx() as con:
        for name in RESTORE_ORDER:
            rows = tables.get(name, [])
            if not rows:
                continue
            allowed = {r[1] for r in con.execute(f'PRAGMA table_info("{name}")')}
            for row in rows:
                cols = [k for k in row if k in allowed]
                marks = ",".join("?" for _ in cols)
                con.execute(f'INSERT INTO "{name}" ({",".join(cols)}) VALUES ({marks})',
                            [row[k] for k in cols])
        # Archives made before the reviewed column existed still contain saved edits.
        if tables.get("questions") and "reviewed" not in tables["questions"][0]:
            con.execute("UPDATE questions SET reviewed=1, reviewed_at=updated_at WHERE edited=1")


def migrate_legacy_media(ctx) -> None:
    """Copy old originals/pages media to documents/images and update stored paths."""
    updates = []
    for table, key, column, old, new in (
        ("documents", "document_id", "file_path", "originals/", "documents/"),
        ("pages", "page_id", "image_path", "pages/", "images/"),
    ):
        for row in ctx.db.query(f"SELECT {key}, {column} FROM {table}"):
            rel = row[column].replace("\\", "/")
            if not rel.startswith(old):
                continue
            target_rel = new + rel[len(old):]
            source, target = ctx.abs_path(rel), ctx.abs_path(target_rel)
            if not target.is_file():
                if not source.is_file():
                    raise FileNotFoundError(f"missing legacy media: {source}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            elif source.is_file() and sha256_file(source) != sha256_file(target):
                raise ValueError(f"legacy media conflict: {target}")
            updates.append((table, key, column, target_rel, row[key]))
    if updates:
        with ctx.db.tx() as con:
            for table, key, column, rel, item_id in updates:
                con.execute(f"UPDATE {table} SET {column}=? WHERE {key}=?", (rel, item_id))


@dataclass
class ArchiveResult:
    path: Path
    folder: Path
    documents: int
    pages: int
    questions: int


def export_workspace_archive(ctx, location: str | Path) -> ArchiveResult:
    """Package every current record and media file, including unfinished pages."""
    with ctx.portable._lock, ctx.db._write_lock:
        return _export_workspace_archive_locked(ctx, location)


def _export_workspace_archive_locked(ctx, location: str | Path) -> ArchiveResult:
    ctx.portable.sync()
    destination = Path(location)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"bndocvqa_archive_{stamp}"
    folder, staging = destination / name, destination / (name + ".partial")
    archive, temporary_zip = destination / (name + ".zip"), destination / (name + ".zip.partial")
    if any(p.exists() for p in (folder, staging, archive, temporary_zip)):
        raise FileExistsError(f"archive already exists: {name}")
    staging.mkdir()
    tables = json.loads((ctx.portable.data / "state.json").read_text(encoding="utf-8"))["tables"]
    for row, key in [(d, "file_path") for d in tables.get("documents", [])] + [
            (p, "image_path") for p in tables.get("pages", [])]:
        rel = Path(row[key])
        source = ctx.abs_path(str(rel))
        if not source.is_file():
            raise FileNotFoundError(f"missing media: {source}")
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        copied_hash = sha256_file(target)
        if copied_hash != sha256_file(source) or (key == "file_path" and copied_hash != row["file_hash"]):
            raise IOError(f"media copy verification failed: {source}")
    shutil.copytree(ctx.portable.data, staging / "data")
    for name_only in ("index.html", "questions.json", "questions.jsonl", "questions.csv"):
        shutil.copy2(ctx.data_dir / name_only, staging / name_only)
    from .export import _write_xlsx
    _write_xlsx(staging / "questions.xlsx", json.loads((staging / "questions.json").read_text(encoding="utf-8")))
    settings_file = ctx.data_dir / "settings.json"
    if settings_file.is_file():
        shutil.copy2(settings_file, staging / "settings.json")
    (staging / "RESTORE.txt").write_text(
        "Bangla DocVQA portable archive.\n"
        "Open index.html to browse the snapshot.\n"
        "To resume in the app, copy this folder's contents into a new workspace folder "
        "and start the app with --data-dir pointing there. The app rebuilds its working "
        "SQLite database from data/state.json when no database exists.\n"
        "API keys are not included.\n", encoding="utf-8")
    files = [{"path": p.relative_to(staging).as_posix(), "bytes": p.stat().st_size,
              "sha256": sha256_file(p)} for p in sorted(staging.rglob("*")) if p.is_file()]
    (staging / "manifest.json").write_bytes(_json_bytes({
        "format_version": FORMAT_VERSION, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "table_counts": {k: len(v) for k, v in tables.items()}, "files": files,
        "saved_questions": sum(bool(q["reviewed"]) for q in tables.get("questions", [])),
        "api_keys_included": False,
    }))
    staging.rename(folder)
    try:
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as zf:
            for file in sorted(folder.rglob("*")):
                if file.is_file():
                    zf.write(file, arcname=(Path(folder.name) / file.relative_to(folder)).as_posix())
        with zipfile.ZipFile(temporary_zip) as zf:
            bad = zf.testzip()
            if bad:
                raise IOError(f"ZIP CRC failed for {bad}")
        os.replace(temporary_zip, archive)
    finally:
        temporary_zip.unlink(missing_ok=True)
    saved_count = sum(bool(q["reviewed"]) for q in tables.get("questions", []))
    return ArchiveResult(archive, folder, len(tables.get("documents", [])),
                         len(tables.get("pages", [])), saved_count)

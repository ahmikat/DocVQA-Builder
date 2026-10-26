"""Export finished documents to a timestamped folder.

    <location>/bndocvqa_export_<YYYYMMDD_HHMMSS>/
      index.html        open in a browser to browse pages and questions
      questions.jsonl   one JSON object per question (UTF-8)
      questions.csv     one row per question (UTF-8 with BOM, opens in Excel)
      questions.xlsx    spreadsheet
      manifest.json     versions, counts, documents, file hashes
      documents/        the original files, byte-for-byte (doc_1.pdf, ...)
      images/           page images (doc_1_p1.png, ...)

Only finished documents (every page processed) are exported. Document and
image paths in records are relative to the export folder.
"""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .. import EXPORT_SCHEMA_VERSION, __version__
from ..models.records import Document, Page, Question, SourcePage
from ..models.taxonomy import TAXONOMY_VERSION, axis_name
from ..prompts import PROMPT_VERSION
from .context import AppContext
from .files import sha256_file
from .viewer_html import render_viewer


class ExportBlocked(Exception):
    pass


@dataclass
class ExportResult:
    path: Path
    documents: int
    questions: int
    skipped_unfinished: list[str]


def document_path(doc: Document) -> str:
    return f"documents/{Path(doc.file_path).name}"


def question_record(q: Question, doc: Document, page: Page,
                    pages: dict[str, Page] | None = None) -> dict:
    page_map = pages or {page.page_id: page}
    source_pages = q.source_pages or [SourcePage(page.page_id, q.evidence_snippet)]
    return {
        "question_id": q.question_id,
        "document_id": q.document_id,
        "document_path": document_path(doc),
        "page_id": q.page_id,
        "page_number": page.page_number,
        "image_path": f"images/{Path(page.image_path).name}",
        "question_bn": q.question_bn,
        "question_format": q.question_format,
        "question_type": q.question_type,
        "options": {o.label: o.text for o in q.options},
        "correct_option": q.correct_option,
        "answer_bn": q.answer_bn,
        "primary_axis": q.primary_axis,
        "axis_name": axis_name(q.primary_axis),
        "sub_axes": list(q.sub_axes),
        "evidence_snippet": q.evidence_snippet,
        "source_pages": [{"page_id": s.page_id, "page_number": page_map[s.page_id].page_number,
                          "image_path": f"images/{Path(page_map[s.page_id].image_path).name}",
                          "evidence_snippet": s.evidence_snippet, "used_for": s.used_for}
                         for s in source_pages],
        "reasoning_steps": list(q.reasoning_steps),
        "rationale": q.rationale,
        "edited": q.edited,
        "reviewed": q.reviewed,
        "reviewed_at": q.reviewed_at,
        "model": q.model,
        "prompt_version": q.prompt_version,
        "source_file": doc.original_filename,
    }


CSV_COLUMNS = ["question_id", "document_id", "document_path", "page_id", "page_number", "image_path", "question_format",
               "question_type", "question_bn", "option_A", "option_B", "option_C", "option_D", "option_E",
               "correct_option", "answer_bn", "primary_axis", "axis_name", "sub_axes", "evidence_snippet",
               "source_pages", "reasoning_steps", "rationale", "edited", "reviewed", "reviewed_at", "model", "prompt_version", "source_file"]


def _flat(r: dict) -> dict:
    out = {k: r[k] for k in CSV_COLUMNS if k in r}
    for lb in "ABCDE":
        out[f"option_{lb}"] = r["options"].get(lb, "")
    out["sub_axes"] = ";".join(r["sub_axes"])
    out["source_pages"] = json.dumps(r["source_pages"], ensure_ascii=False)
    out["reasoning_steps"] = json.dumps(r["reasoning_steps"], ensure_ascii=False)
    return out


def _write_xlsx(path: Path, records: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "questions"
    ws.append(CSV_COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True, name="Nirmala UI")
        c.fill = PatternFill("solid", fgColor="DDE3EA")
    body, wrap = Font(name="Nirmala UI"), Alignment(wrap_text=True, vertical="top")
    for i, r in enumerate(records, start=2):
        flat = _flat(r)
        ws.append([flat[c] for c in CSV_COLUMNS])
        for c in ws[i]:
            c.font, c.alignment = body, wrap
    widths = {"question_bn": 50, "rationale": 40, "evidence_snippet": 40, "answer_bn": 25,
              **{f"option_{lb}": 22 for lb in "ABCDE"}}
    for j, name in enumerate(CSV_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(j)].width = widths.get(name, 14)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def finished_documents(ctx: AppContext, document_ids: Iterable[str] | None = None) -> tuple[list[str], list[str]]:
    """Split the given (or all) documents into (finished, unfinished)."""
    ids = list(document_ids) if document_ids is not None else [d.document_id for d in ctx.documents.list()]
    done = [d for d in ids if ctx.documents.is_finished(d)]
    return done, [d for d in ids if d not in done]


def _doc_order(doc_id: str) -> int:
    try:
        return int(doc_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def export_dataset(ctx: AppContext, location: str | Path, document_ids: Iterable[str] | None = None) -> ExportResult:
    finished, unfinished = finished_documents(ctx, document_ids)
    if not finished:
        raise ExportBlocked("No finished documents to export. Process documents first.")
    now = datetime.now()
    root = Path(location) / f"bndocvqa_export_{now:%Y%m%d_%H%M%S}"
    if root.exists():
        raise ExportBlocked(f"{root} already exists")
    (root / "images").mkdir(parents=True)
    (root / "documents").mkdir()

    docs = {d: ctx.documents.get(d) for d in finished}
    for d in docs.values():
        dst = root / document_path(d)
        shutil.copyfile(ctx.abs_path(d.file_path), dst)  # copyfile: the export copy stays writable
        if sha256_file(dst) != d.file_hash:
            raise ExportBlocked(f"{d.document_id}: stored original does not match its recorded hash")
    pages = {p.page_id: p for d in finished for p in ctx.pages.for_document(d)}
    for p in pages.values():
        shutil.copy2(ctx.abs_path(p.image_path), root / "images" / Path(p.image_path).name)
    records = [question_record(q, docs[q.document_id], pages[q.page_id], pages)
               for q in ctx.questions.for_documents(finished) if q.reviewed]
    records.sort(key=lambda r: (_doc_order(r["document_id"]), r["page_number"], r["question_id"]))

    with open(root / "questions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(root / "questions.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in records:
            w.writerow(_flat(r))
    _write_xlsx(root / "questions.xlsx", records)
    page_list = [{"page_id": p.page_id, "document_id": p.document_id, "page_number": p.page_number,
                  "image_path": f"images/{Path(p.image_path).name}", "content_type": p.content_type,
                  "content_note": p.content_note}
                 for p in sorted(pages.values(), key=lambda p: (_doc_order(p.document_id), p.page_number))]
    doc_paths = {d.document_id: document_path(d) for d in docs.values()}
    (root / "index.html").write_text(render_viewer(records, page_list, now, doc_paths), encoding="utf-8")

    files = [{"path": f.relative_to(root).as_posix(), "bytes": f.stat().st_size, "sha256": sha256_file(f)}
             for f in sorted(root.rglob("*")) if f.is_file()]
    axes: dict[str, int] = {}
    for r in records:
        axes[r["primary_axis"]] = axes.get(r["primary_axis"], 0) + 1
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION, "app_version": __version__, "taxonomy_version": TAXONOMY_VERSION,
        "prompt_version": PROMPT_VERSION, "exported_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "documents": [{"document_id": d.document_id, "document_path": document_path(d),
                       "source_file": d.original_filename, "file_hash": d.file_hash,
                       "page_count": d.page_count,
                       "pages": [pg for pg in page_list if pg["document_id"] == d.document_id]}
                      for d in sorted(docs.values(), key=lambda d: _doc_order(d.document_id))],
        "question_count": len(records), "questions_by_axis": dict(sorted(axes.items())),
        "edited_questions": sum(r["edited"] for r in records), "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return ExportResult(root, len(docs), len(records), unfinished)

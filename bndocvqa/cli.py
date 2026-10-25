"""Command-line interface. Run `python -m bndocvqa --help`. With no command, the app opens."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ctx(args):
    from .services.context import open_context
    return open_context(args.data_dir)


def _print(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def cmd_import(args):
    from .services.library import SUPPORTED_EXTS, LibraryService
    files: list[Path] = []
    for p in map(Path, args.paths):
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_EXTS) if p.is_dir() else [p]
    ctx = _ctx(args)
    res = LibraryService(ctx).import_files(files)
    ctx.portable.sync()
    _print({"imported": [(d.document_id, d.original_filename, d.page_count) for d in res.imported],
            "duplicates": [(str(p), d.document_id) for p, d in res.duplicates],
            "failed": [(str(p), e) for p, e in res.failed]})
    return 1 if res.failed else 0


def cmd_list(args):
    ctx = _ctx(args)
    counts = ctx.questions.counts_by_document()
    status = ctx.documents.page_status_counts()
    for d in ctx.documents.list():
        st = status.get(d.document_id, {})
        sys.stdout.write(f"{d.document_id}\t{d.page_count}p\tdone={st.get('done', 0)}\tfailed={st.get('failed', 0)}\t"
                         f"{counts.get(d.document_id, 0)}q\t{d.original_filename}\n")


def cmd_process(args):
    from .services.gemini import GeminiProvider
    from .services.gemini.usage import RequestLog
    from .services.pipeline import Pipeline
    from .workers.queue import JobRunner
    ctx = _ctx(args)
    if not args.document_ids:
        sys.stderr.write("give the document ids to process (e.g. doc_1 doc_2)\n")
        return 2
    pl = Pipeline(ctx)
    n = sum(len(pl.process_document(d)) for d in args.document_ids)
    sys.stdout.write(f"queued {n} page(s)\n")
    runner = JobRunner(ctx, lambda: GeminiProvider(ctx.settings, request_log=RequestLog(ctx.db)),
                       on_event=lambda ev, j: sys.stdout.write(f"{ev}\t{j.page_id}\t{j.result_summary or j.error}\n"))
    runner.run_until_idle()
    ctx.portable.sync()


def cmd_export(args):
    from .services.portable import export_workspace_archive
    try:
        res = export_workspace_archive(_ctx(args), args.location)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"export failed: {e}\n")
        return 2
    _print({"zip": str(res.path), "folder": str(res.folder), "documents": res.documents,
            "pages": res.pages, "questions": res.questions})


def cmd_evaluate(args):
    from .services.evaluation import evaluate, load_jsonl, load_references, write_per_question_csv
    res = evaluate(load_references(args.references), load_jsonl(args.predictions))
    if args.per_question_csv:
        write_per_question_csv(res, args.per_question_csv)
    _print({k: v for k, v in res.items() if k != "per_question"})


def cmd_gui(args):
    from .ui.app import run
    return run(args.data_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bndocvqa", description="Bangla DocVQA benchmark dataset builder")
    p.add_argument("--data-dir", default=None, help="data directory (default: ./workspace)")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("gui", help="open the app (default)")
    s.set_defaults(func=cmd_gui)
    s = sub.add_parser("import", help="import PDFs/images (files or folders) as doc_1, doc_2, ...")
    s.add_argument("paths", nargs="+")
    s.set_defaults(func=cmd_import)
    s = sub.add_parser("list", help="list documents and their progress")
    s.set_defaults(func=cmd_list)
    s = sub.add_parser("process", help="generate questions for documents (one Gemini request per page)")
    s.add_argument("document_ids", nargs="*")
    s.set_defaults(func=cmd_process)
    s = sub.add_parser("export", help="archive all current data and media as a ZIP")
    s.add_argument("location")
    s.set_defaults(func=cmd_export)
    s = sub.add_parser("evaluate", help="score model predictions against an exported questions.jsonl")
    s.add_argument("references")
    s.add_argument("predictions")
    s.add_argument("--per-question-csv")
    s.set_defaults(func=cmd_evaluate)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        args.func = cmd_gui
    return int(args.func(args) or 0)

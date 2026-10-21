"""Document library: import (auto-named doc_1, doc_2, ...), page rendering, removal."""
from __future__ import annotations

import logging
import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

import pymupdf
from PIL import Image, ImageOps

from ..database import utcnow
from ..models.records import Document, Page
from .context import AppContext
from .files import safe_relative, sha256_file

log = logging.getLogger(__name__)

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS


@dataclass
class ImportResult:
    imported: list[Document] = field(default_factory=list)
    duplicates: list[tuple[Path, Document]] = field(default_factory=list)  # (path, existing doc)
    failed: list[tuple[Path, str]] = field(default_factory=list)


class LibraryService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.s = ctx.settings

    def import_files(self, paths: Iterable[str | Path],
                     progress: Callable[[int, int, str], None] | None = None) -> ImportResult:
        """Import PDFs/images in the given order. Duplicates (same SHA-256) are skipped."""
        paths = [Path(p) for p in paths]
        res = ImportResult()
        for i, p in enumerate(paths):
            if progress:
                progress(i, len(paths), p.name)
            try:
                if p.suffix.lower() not in SUPPORTED_EXTS:
                    raise ValueError(f"unsupported file type {p.suffix}")
                doc, existing = self.import_file(p)
                if existing is not None:
                    res.duplicates.append((p, existing))
                else:
                    res.imported.append(doc)
            except Exception as e:  # report per file and continue the batch
                log.exception("import failed for %s", p)
                res.failed.append((p, str(e)))
        if progress:
            progress(len(paths), len(paths), "")
        return res

    def import_file(self, path: str | Path) -> tuple[Optional[Document], Optional[Document]]:
        """Import one file as the next doc_N. Returns (new_doc, None) or (None, existing_duplicate)."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        file_hash = sha256_file(path)
        existing = self.ctx.documents.by_hash(file_hash)
        if existing is not None:
            return None, existing

        written: list[Path] = []
        try:
            with self.ctx.db.tx() as con:
                doc_id = f"doc_{self.ctx.documents.next_number(con)}"
                dest = self.s.originals_dir / f"{doc_id}{path.suffix.lower()}"
                if dest.exists():
                    raise FileExistsError(dest)
                shutil.copy2(path, dest)
                written.append(dest)
                if sha256_file(dest) != file_hash:
                    raise IOError(f"copy verification failed for {path}")
                os.chmod(dest, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
                doc = Document(document_id=doc_id, original_filename=path.name,
                               file_path=safe_relative(dest, self.s.data_dir), file_hash=file_hash,
                               imported_at=utcnow())
                pages = self._render(doc, dest, written)
                doc.page_count = len(pages)
                self.ctx.documents.insert(doc, con)
                for pg in pages:
                    self.ctx.pages.insert(pg, con)
        except Exception:
            for w in written:
                _make_writable(w)
                w.unlink(missing_ok=True)
            raise
        log.info("imported %s as %s (%d pages)", path.name, doc.document_id, doc.page_count)
        return doc, None

    def _render(self, doc: Document, original: Path, written: list[Path]) -> list[Page]:
        ext = "jpg" if self.s.page_image_format.lower() in ("jpg", "jpeg") else "png"
        pages: list[Page] = []

        def out_path(n: int) -> Path:
            p = self.s.pages_dir / f"{doc.document_id}_p{n}.{ext}"
            if p.exists():
                raise FileExistsError(p)
            return p

        if original.suffix.lower() in PDF_EXTS:
            with pymupdf.open(original) as pdf:
                if pdf.needs_pass:
                    raise ValueError("encrypted PDF")
                for i, pg in enumerate(pdf, start=1):
                    out = out_path(i)
                    pix = pg.get_pixmap(dpi=self.s.render_dpi, alpha=False)
                    if ext == "png":
                        pix.save(out)
                    else:
                        pix.pil_save(out, format="JPEG", quality=92)
                    written.append(out)
                    pages.append(self._page(doc, i, out, pix.width, pix.height))
        else:
            out = out_path(1)
            with Image.open(original) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.save(out, **({"quality": 92} if ext == "jpg" else {}))
                w, h = im.size
            written.append(out)
            pages.append(self._page(doc, 1, out, w, h))
        return pages

    def _page(self, doc: Document, n: int, out: Path, w: int, h: int) -> Page:
        return Page(page_id=f"{doc.document_id}_p{n}", document_id=doc.document_id, page_number=n,
                    image_path=safe_relative(out, self.s.data_dir), width=w, height=h)

    def remove_document(self, document_id: str) -> Path:
        """Remove the records; the document's files are moved to trash, not deleted."""
        doc = self.ctx.documents.get(document_id)
        if doc is None:
            raise KeyError(document_id)
        pages = self.ctx.pages.for_document(document_id)
        self.ctx.jobs.cancel_for_document(document_id)
        trash = self.s.data_dir / "trash" / f"{document_id}_{datetime.now():%Y%m%d%H%M%S}"
        trash.mkdir(parents=True)
        self.ctx.documents.delete(document_id)
        for rel in [doc.file_path, *(p.image_path for p in pages)]:
            src = self.s.data_dir / rel
            if src.exists():
                _make_writable(src)
                target = trash / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), target)
        return trash


def _make_writable(p: Path) -> None:
    try:
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    except FileNotFoundError:
        pass

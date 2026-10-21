"""Library: import, tick documents, process, view, export."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QProgressDialog, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..services.context import AppContext
from ..services.export import ExportBlocked, export_dataset
from ..services.library import SUPPORTED_EXTS, LibraryService

COLS = ["", "Name", "File", "Pages", "Questions", "Status"]
STATUS_COLORS = {"finished": "#15803d", "processing": "#2563eb", "waiting": "#b45309", "failed": "#b91c1c",
                 "partial": "#7c3aed", "new": "#6b7280"}


class LibraryView(QWidget):
    openDocument = Signal(str)
    status = Signal(str)
    changed = Signal()
    processRequested = Signal(list)  # document ids
    keysRequested = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.lib = LibraryService(ctx)
        self._checked: set[str] = set()

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(lambda r, c: self.openDocument.emit(self.table.item(r, 1).text()))

        def btn(text, fn, tip=""):
            b = QPushButton(text)
            b.clicked.connect(fn)
            b.setToolTip(tip)
            return b
        bar = QHBoxLayout()
        bar.addWidget(btn("Import files…", self.import_files, "Add PDFs or images; they are named doc_1, doc_2, …"))
        bar.addWidget(btn("Import folder…", self.import_folder))
        bar.addWidget(btn("▶ Process", self._process, "Generate questions for the ticked documents"))
        bar.addWidget(btn("View", self._view, "Open the ticked (or highlighted) document in the View tab"))
        bar.addWidget(btn("Export…", self._export, "Export finished documents (ticked ones, or all if none ticked)"))
        bar.addStretch(1)
        bar.addWidget(btn("Select all", lambda: self._set_all(True)))
        bar.addWidget(btn("Clear", lambda: self._set_all(False)))
        bar.addWidget(btn("Remove…", self.remove_checked, "Remove the ticked documents (files go to trash)"))
        bar.addWidget(btn("Gemini API keys…", self.keysRequested.emit, "Add, remove and test API keys; pick the model"))
        self.summary = QLabel()
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)

        self.timer = QTimer(self, interval=1500, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    # -- table ------------------------------------------------------------------
    def _doc_status(self, pages: int, st: dict, active: list) -> tuple[str, str]:
        done, failed = st.get("done", 0), st.get("failed", 0)
        if active:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if all(j.next_attempt_at and j.next_attempt_at > now and "daily quota" in j.error for j in active):
                return "waiting", f"⏸ Waiting for daily quota ({done}/{pages} pages)"
            return "processing", f"⏳ Processing… {done}/{pages} pages"
        if pages and done == pages:
            return "finished", "✔ Finished"
        if failed:
            return "failed", f"⚠ {failed} page(s) failed — Process again to retry"
        if done:
            return "partial", f"◐ {done}/{pages} pages — Process to finish"
        return "new", "Not processed"

    def refresh(self) -> None:
        docs = self.ctx.documents.list()
        counts = self.ctx.questions.counts_by_document()
        st = self.ctx.documents.page_status_counts()
        active: dict[str, list] = {}
        for j in self.ctx.jobs.list(statuses=("queued", "running")):
            active.setdefault(j.document_id, []).append(j)
        self._checked &= {d.document_id for d in docs}
        self.table.blockSignals(True)
        self.table.setRowCount(len(docs))
        totals = {"finished": 0, "processing": 0, "waiting": 0}
        for r, d in enumerate(docs):
            key, text = self._doc_status(d.page_count, st.get(d.document_id, {}), active.get(d.document_id, []))
            if key in totals:
                totals[key] += 1
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if d.document_id in self._checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, d.document_id)
            self.table.setItem(r, 0, chk)
            for c, v in enumerate((d.document_id, d.original_filename, d.page_count,
                                   counts.get(d.document_id, 0)), start=1):
                it = QTableWidgetItem(str(v))
                if c in (3, 4):
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            s = QTableWidgetItem(text)
            s.setForeground(QBrush(QColor(STATUS_COLORS[key])))
            self.table.setItem(r, 5, s)
        self.table.blockSignals(False)
        self.summary.setText(f"{len(docs)} document(s) · {totals['finished']} finished · "
                             f"{totals['processing']} processing · {totals['waiting']} waiting for quota · "
                             f"{len(self._checked)} ticked")

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            doc_id = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                self._checked.add(doc_id)
            else:
                self._checked.discard(doc_id)
            self.refresh()

    def _set_all(self, on: bool) -> None:
        self._checked = {d.document_id for d in self.ctx.documents.list()} if on else set()
        self.refresh()

    def checked_ids(self) -> list[str]:
        return [d.document_id for d in self.ctx.documents.list() if d.document_id in self._checked]

    # -- import -----------------------------------------------------------------
    def import_files(self):
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Import documents", "", f"Documents ({exts})")
        if paths:
            self._import(sorted(paths))

    def import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Import all PDFs/images in folder")
        if d:
            paths = sorted(str(p) for p in Path(d).rglob("*") if p.suffix.lower() in SUPPORTED_EXTS)
            if not paths:
                QMessageBox.information(self, "Import", "No PDFs or images found in that folder.")
                return
            self._import(paths)

    def _import(self, paths):
        prog = QProgressDialog("Importing…", "", 0, len(paths), self)
        prog.setCancelButton(None)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def cb(i, n, name):
            prog.setValue(i)
            prog.setLabelText(f"Rendering {name}…")
            QApplication.processEvents()
        res = self.lib.import_files(paths, cb)
        prog.close()
        msg = [f"Imported {len(res.imported)} document(s)"
               + (f": {res.imported[0].document_id} … {res.imported[-1].document_id}." if res.imported else ".")]
        if res.duplicates:
            msg.append(f"\nSkipped {len(res.duplicates)} file(s) already in the library:")
            msg += [f"  • {p.name} = {d.document_id}" for p, d in res.duplicates[:15]]
        if res.failed:
            msg.append(f"\n{len(res.failed)} failed:")
            msg += [f"  • {p.name}: {e}" for p, e in res.failed[:15]]
        (QMessageBox.warning if res.failed else QMessageBox.information)(self, "Import finished", "\n".join(msg))
        self.refresh()
        self.changed.emit()

    # -- actions ----------------------------------------------------------------
    def _process(self):
        ids = self.checked_ids()
        if not ids:
            QMessageBox.information(self, "Process", "Tick the documents you want to process.")
            return
        self.processRequested.emit(ids)

    def _view(self):
        ids = self.checked_ids()
        row = self.table.currentRow()
        doc_id = ids[0] if ids else (self.table.item(row, 1).text() if row >= 0 else None)
        if doc_id:
            self.openDocument.emit(doc_id)

    def _export(self):
        location = QFileDialog.getExistingDirectory(self, "Choose where to save the export")
        if not location:
            return
        try:
            res = export_dataset(self.ctx, location, self.checked_ids() or None)
        except ExportBlocked as e:
            QMessageBox.warning(self, "Export", str(e))
            return
        note = (f"\n\nSkipped {len(res.skipped_unfinished)} unfinished document(s): "
                f"{', '.join(res.skipped_unfinished[:10])}" if res.skipped_unfinished else "")
        box = QMessageBox(QMessageBox.Information, "Export finished",
                          f"Exported {res.documents} document(s), {res.questions} question(s) to:\n{res.path}{note}",
                          parent=self)
        open_btn = box.addButton("Open index.html", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(res.path / "index.html")))

    def remove_checked(self):
        ids = self.checked_ids()
        if not ids:
            QMessageBox.information(self, "Remove", "Tick the documents you want to remove.")
            return
        if QMessageBox.warning(self, "Remove documents",
                               f"Remove {len(ids)} document(s) ({', '.join(ids[:8])}) and their questions?\n\n"
                               "The files are moved to the workspace trash folder, not deleted.",
                               QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        for d in ids:
            self.lib.remove_document(d)
        self._checked -= set(ids)
        self.refresh()
        self.changed.emit()

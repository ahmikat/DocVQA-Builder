"""Library: import, tick documents, process, view, export."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QProgressDialog, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..services.context import AppContext
from ..services.portable import export_workspace_archive
from ..services.library import SUPPORTED_EXTS, LibraryService
from ..services.question_limits import max_questions_for_document

COLS = ["", "Name", "File", "Pages", "Questions", "Saved", "Gemini Generated"]
STATUS_COLORS = {"finished": "#55d6b1", "processing": "#8bb8ff", "waiting": "#f3c779",
                 "failed": "#ff99aa", "partial": "#c6a8ff", "new": "#a9bbd2"}


def _open_local_html(path: Path) -> bool:
    """Use the Windows file association first, then Qt's cross-platform opener."""
    if os.name == "nt":
        try:
            os.startfile(str(path))
            return True
        except OSError:
            pass
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class LibraryView(QWidget):
    openDocument = Signal(str)
    chatImported = Signal(str, str)  # document_id, first new question_id
    status = Signal(str)
    changed = Signal()
    processRequested = Signal(list)  # document ids
    keysRequested = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.setObjectName("libraryPage")
        self.ctx = ctx
        self.lib = LibraryService(ctx)
        self._checked: set[str] = set()

        hero = QFrame()
        hero.setObjectName("hero")
        hero_lay = QVBoxLayout(hero)
        hero_lay.setContentsMargins(16, 11, 16, 11)
        hero_lay.setSpacing(3)
        eyebrow = QLabel("BANGLA DOCVQA  /  DATASET WORKSPACE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Document library")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Import documents, generate questions, review each answer, then export your saved set.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        hero_lay.addWidget(eyebrow)
        hero_lay.addWidget(title)
        hero_lay.addWidget(subtitle)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.metric_values = {}
        for key, label in (("documents", "Documents"), ("generated", "Generated questions"),
                           ("saved", "Saved for export"), ("finished", "Gemini finished")):
            card = QFrame()
            card.setObjectName("metricCard")
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(12, 7, 12, 7)
            card_lay.setSpacing(1)
            value = QLabel("0")
            value.setObjectName("metricValue")
            caption = QLabel(label)
            caption.setObjectName("metricLabel")
            card_lay.addWidget(value)
            card_lay.addWidget(caption)
            self.metric_values[key] = value
            metrics.addWidget(card, 1)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeaderItem(4).setToolTip("Generated questions / document maximum")
        self.table.horizontalHeaderItem(5).setToolTip("Manually saved questions / generated questions")
        self.table.horizontalHeaderItem(6).setToolTip("Finished when all pages have been processed")
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
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
        actions = QFrame()
        actions.setObjectName("toolbarSurface")
        action_lay = QVBoxLayout(actions)
        action_lay.setContentsMargins(11, 9, 11, 9)
        action_lay.setSpacing(7)
        primary = QHBoxLayout()
        primary.setSpacing(7)
        primary.addWidget(btn("Import files…", self.import_files, "Add PDFs or images; they are named doc_1, doc_2, …"))
        primary.addWidget(btn("Import folder…", self.import_folder))
        primary.addWidget(btn("Generate questions", self._process, "Generate questions for the ticked documents"))
        primary.addWidget(btn("Review questions", self._view,
                              "Open the ticked (or highlighted) document for editing"))
        primary.addWidget(btn("View", self._open_data_viewer,
                              "Open the HTML overview of saved questions and document pages"))
        primary.addWidget(btn("Export ZIP…", self._export, "Archive all current data, documents and images"))
        primary.addStretch(1)
        primary.addWidget(btn("Gemini API keys…", self.keysRequested.emit, "Add, remove and test API keys; pick the model"))
        action_lay.addLayout(primary)
        secondary = QHBoxLayout()
        secondary.setSpacing(7)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search document name or filename…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        self.search.textChanged.connect(self._apply_filter)
        secondary.addWidget(self.search, 1)
        secondary.addWidget(btn("Paste Gemini JSON…", self.import_chat_questions,
                                "Match pasted questions to existing documents and stage drafts for manual review"))
        secondary.addWidget(btn("Select all", lambda: self._set_all(True)))
        secondary.addWidget(btn("Clear", lambda: self._set_all(False)))
        secondary.addWidget(btn("Remove…", self.remove_checked, "Remove the ticked documents (files go to trash)"))
        action_lay.addLayout(secondary)

        table_surface = QFrame()
        table_surface.setObjectName("surface")
        table_lay = QVBoxLayout(table_surface)
        table_lay.setContentsMargins(10, 9, 10, 10)
        table_lay.setSpacing(7)
        section = QLabel("Documents")
        section.setObjectName("sectionTitle")
        section_hint = QLabel("Double-click a row to review its questions")
        section_hint.setObjectName("sectionHint")
        section_line = QHBoxLayout()
        section_line.addWidget(section)
        section_line.addStretch(1)
        section_line.addWidget(section_hint)
        table_lay.addLayout(section_line)
        table_lay.addWidget(self.table, 1)
        self.empty_state = QLabel("Your library is empty. Import a PDF or image to get started.")
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setWordWrap(True)
        table_lay.addWidget(self.empty_state, 1)
        self.summary = QLabel()
        self.summary.setObjectName("helper")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 11)
        lay.setSpacing(9)
        lay.addWidget(hero)
        lay.addLayout(metrics)
        lay.addWidget(actions)
        lay.addWidget(table_surface, 1)
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
                return "waiting", f"Unfinished · quota wait ({done}/{pages})"
            return "processing", f"Unfinished · generating ({done}/{pages})"
        if pages and done == pages:
            return "finished", "Finished"
        if failed:
            return "failed", f"Unfinished · {failed} failed (retry)"
        if done:
            return "partial", f"Unfinished · {done}/{pages} pages"
        return "new", "Unfinished"

    def refresh(self) -> None:
        docs = self.ctx.documents.list()
        counts = self.ctx.questions.counts_by_document()
        saved_counts = self.ctx.questions.reviewed_counts_by_document()
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
                                   f"{counts.get(d.document_id, 0)}/{max_questions_for_document(d.page_count)}",
                                   f"{saved_counts.get(d.document_id, 0)}/{counts.get(d.document_id, 0)}"), start=1):
                it = QTableWidgetItem(str(v))
                if c in (3, 4, 5):
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            s = QTableWidgetItem(text)
            s.setForeground(QBrush(QColor(STATUS_COLORS[key])))
            font = s.font()
            font.setBold(True)
            s.setFont(font)
            self.table.setItem(r, 6, s)
        self.table.blockSignals(False)
        self.table.setVisible(bool(docs))
        self.empty_state.setVisible(not docs)
        self.metric_values["documents"].setText(str(len(docs)))
        self.metric_values["generated"].setText(str(sum(counts.values())))
        self.metric_values["saved"].setText(str(sum(saved_counts.values())))
        self.metric_values["finished"].setText(str(totals["finished"]))
        self._apply_filter()
        self.summary.setText(f"{len(docs)} document(s) · {totals['finished']} finished · "
                             f"{totals['processing']} processing · {totals['waiting']} waiting for quota · "
                             f"{len(self._checked)} ticked"
                             + (" · Data file sync failed; check logs" if self.ctx.db.last_mirror_error else ""))

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 1)
            source = self.table.item(row, 2)
            searchable = f"{name.text() if name else ''} {source.text() if source else ''}".casefold()
            self.table.setRowHidden(row, bool(needle) and needle not in searchable)

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
    def import_chat_questions(self):
        from .chat_import_dialog import ChatImportDialog
        dialog = ChatImportDialog(self.ctx, self)
        if dialog.exec() == dialog.Accepted:
            self.refresh()
            self.changed.emit()
            self.chatImported.emit(dialog.document_id, dialog.created_ids[0] if dialog.created_ids else "")

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
            res = export_workspace_archive(self.ctx, location)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Export", str(e))
            return
        box = QMessageBox(QMessageBox.Information, "Export finished",
                          f"Archived {res.documents} document(s), {res.pages} page(s), "
                          f"{res.questions} saved question(s) to:\n{res.path}",
                          parent=self)
        open_btn = box.addButton("Open index.html", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is open_btn:
            if not _open_local_html(res.folder / "index.html"):
                QMessageBox.warning(self, "Export", "Could not open the exported index.html in a browser.")

    def _open_data_viewer(self):
        try:
            self.ctx.portable.sync()
        except Exception as exc:
            QMessageBox.warning(self, "Data viewer", f"Could not update the HTML viewer:\n{exc}")
            return
        path = (self.ctx.data_dir / "index.html").resolve()
        if not _open_local_html(path):
            QMessageBox.warning(self, "Data viewer", f"Could not open the browser. Open this file manually:\n{path}")
        else:
            self.status.emit(f"Opened saved-question HTML: {path}")

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

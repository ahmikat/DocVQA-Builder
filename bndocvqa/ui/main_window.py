"""Main window: Library and View tabs, plus the background processing runner."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QTabWidget

from ..services.context import AppContext
from ..services.pipeline import Pipeline
from .library_view import LibraryView
from .style import apply_button_roles
from .view_view import ViewTab


class _Bridge(QObject):
    jobEvent = Signal(str, str)  # event, document_id (emitted from worker threads)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.runner = None
        self.bridge = _Bridge()
        self.bridge.jobEvent.connect(self._on_job_event)
        self.setWindowTitle("Bangla DocVQA Builder")
        self.resize(1500, 920)

        self.library = LibraryView(ctx)
        self.view = ViewTab(ctx)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.library, "Library")
        self.tabs.addTab(self.view, "View")
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._tab_changed)

        self.library.openDocument.connect(self._open_document)
        self.library.processRequested.connect(self.process_documents)
        self.library.keysRequested.connect(self._keys)
        self.library.changed.connect(self.view.reload_documents)
        self.view.questionsChanged.connect(self.library.refresh)
        for v in (self.library, self.view):
            v.status.connect(lambda m: self.statusBar().showMessage(m, 8000))

        self._quota = QLabel()
        self.statusBar().addPermanentWidget(self._quota)
        self._update_quota()
        apply_button_roles(self)
        # Resume pages left queued by a previous session (e.g. waiting for the daily quota).
        self.ctx.jobs.recover_interrupted()
        if self.ctx.jobs.list(statuses=("queued",)) and self.ctx.settings.gemini_keys:
            self.start_runner()

    def _tab_changed(self, i: int) -> None:
        if self.tabs.widget(i) is self.view:
            self.view.reload_documents()
        else:
            self.library.refresh()

    def _open_document(self, document_id: str) -> None:
        self.tabs.setCurrentWidget(self.view)
        self.view.open_document(document_id)

    def _update_quota(self) -> None:
        from ..services.gemini.usage import quota_summary
        s = self.ctx.settings
        self._quota.setText(f"{len(s.gemini_keys)} key(s) · {quota_summary(s, self.ctx.db)}")

    # -- processing ---------------------------------------------------------------
    def process_documents(self, ids: list[str]) -> None:
        if not self.ctx.settings.gemini_keys:
            self._keys()
            if not self.ctx.settings.gemini_keys:
                return
        pl = Pipeline(self.ctx)
        pages = sum(len(pl.process_document(d)) for d in ids)
        if not pages:
            self.statusBar().showMessage("The ticked documents are already finished.", 8000)
            return
        self.statusBar().showMessage(f"Processing {pages} page(s) from {len(ids)} document(s)…", 10000)
        self.start_runner()
        self.library.refresh()

    def start_runner(self) -> None:
        from ..services.gemini import GeminiProvider
        from ..services.gemini.usage import RequestLog
        from ..workers.queue import JobRunner
        if self.runner and self.runner.running:
            return
        self.runner = JobRunner(self.ctx, lambda: GeminiProvider(self.ctx.settings, request_log=RequestLog(self.ctx.db)),
                                on_event=lambda ev, j: self.bridge.jobEvent.emit(ev, j.document_id))
        self.runner.start()

    def stop_runner(self) -> None:
        if self.runner:
            self.runner.stop()

    def _on_job_event(self, event: str, document_id: str) -> None:
        self._update_quota()
        if event in ("succeeded", "failed"):
            self.library.refresh()
            if self.view.document_id == document_id:
                self.view.reload_documents()

    def _keys(self) -> None:
        from .keys_dialog import GeminiKeysDialog
        GeminiKeysDialog(self.ctx, self).exec()
        self._update_quota()
        if self.runner and self.runner.running:  # pick up new keys / model
            self.stop_runner()
            self.start_runner()

    def closeEvent(self, e):
        if self.ctx.jobs.list(statuses=("running",)) and QMessageBox.question(
                self, "Quit", "Processing is running. Quit anyway? Unfinished pages resume next time you open "
                "the app.") != QMessageBox.Yes:
            e.ignore()
            return
        self.stop_runner()
        e.accept()

"""Paste a Gemini chat JSON batch, inspect its document match, and stage drafts."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from ..services.chat_import import prepare_chat_import, stage_chat_import


class ChatImportDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.prepared = None
        self.created_ids: list[str] = []
        self.document_id = ""
        self.setWindowTitle("Import Gemini chat questions")
        self.resize(920, 720)
        layout = QVBoxLayout(self)
        intro = QLabel("Paste one gemini_chat_multipage_v1 JSON batch, or load a UTF-8 .json/.txt file. "
                       "Check the matched document and pages before staging. Staged drafts appear in View; "
                       "only questions you manually Save enter the dataset exports.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText('{"schema_version":"gemini_chat_multipage_v1", "document_id":"doc_7", "questions":[...]}')
        self.input.textChanged.connect(self._changed)
        layout.addWidget(self.input, 1)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(165)
        self.summary.setPlaceholderText("Select Preview match to validate the JSON and see the matched source file.")
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        open_btn = QPushButton("Load JSON/TXT…")
        open_btn.clicked.connect(self._load_file)
        preview_btn = QPushButton("Preview match")
        preview_btn.clicked.connect(self.preview)
        self.stage_btn = QPushButton("Stage drafts for review")
        self.stage_btn.setEnabled(False)
        self.stage_btn.clicked.connect(self.stage)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        for button in (open_btn, preview_btn, self.stage_btn, close_btn):
            actions.addWidget(button)
        layout.addLayout(actions)

    def _changed(self) -> None:
        self.prepared = None
        self.stage_btn.setEnabled(False)
        self.summary.clear()

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Gemini chat JSON", "", "JSON or text (*.json *.txt);;All files (*)")
        if path:
            try:
                self.input.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError) as exc:
                QMessageBox.warning(self, "Cannot load file", str(exc))

    def preview(self) -> None:
        try:
            prepared = prepare_chat_import(self.ctx, self.input.toPlainText())
        except ValueError as exc:
            self._changed()
            self.summary.setPlainText(str(exc))
            QMessageBox.warning(self, "Cannot import questions", str(exc))
            return
        self.prepared = prepared
        self.stage_btn.setEnabled(True)
        multi = sum(len(q.source_pages) > 1 for q in prepared.questions)
        lines = [f"Matched: {prepared.document_id} — {prepared.document_name} ({prepared.page_count} pages)",
                 f"Valid questions: {len(prepared.questions)}; multi-page: {multi}; already present: {prepared.existing}",
                 "Matched by document_id and page IDs. Confirm this is the same source PDF/image used in Gemini chat.",
                 "Drafts are kept out of questions.jsonl/CSV until each question is manually Saved."]
        if prepared.warnings:
            lines.append("Review warnings:")
            lines.extend(f"• {w}" for w in prepared.warnings)
        self.summary.setPlainText("\n".join(lines))

    def stage(self) -> None:
        if self.prepared is None:
            return
        try:
            self.created_ids = stage_chat_import(self.ctx, self.prepared)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        try:
            self.ctx.portable.sync()
        except Exception as exc:
            self.ctx.db.last_mirror_error = str(exc)
            QMessageBox.warning(self, "Dataset files",
                                f"Drafts are saved in SQLite, but workspace JSON/CSV sync failed:\n{exc}")
        self.document_id = self.prepared.document_id
        QMessageBox.information(self, "Drafts staged",
                                f"Added {len(self.created_ids)} new draft(s) for {self.document_id}. "
                                f"Skipped {len(self.prepared.questions) - len(self.created_ids)} existing question(s). "
                                "Review each in View and click Save to include it in workspace dataset files.")
        self.accept()

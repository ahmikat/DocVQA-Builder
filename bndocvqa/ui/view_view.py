"""View tab: browse a document's pages and edit its generated questions."""
from __future__ import annotations

import copy
import math
from collections import Counter
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from ..models.records import Option, Question
from ..models.taxonomy import (ABSTAIN_TEXT, AXES, FORMAT_VERIFY3, MCQ5_LABELS, VERIFY3_LABELS, VERIFY3_OPTIONS, expected_format,
                               expected_type, labels_for)
from ..models.text import normalize_answer
from ..services.context import AppContext
from .page_viewer import PageViewer


class AutoHeightQuestionEdit(QPlainTextEdit):
    """Show the complete wrapped question while the surrounding editor scrolls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fitting = False
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.textChanged.connect(self.fit_to_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_to_text()

    def fit_to_text(self):
        if self._fitting or self.viewport().width() < 100:
            return
        self._fitting = True
        try:
            probe = QTextDocument()
            probe.setDefaultFont(self.font())
            probe.setDocumentMargin(0)
            probe.setPlainText(self.toPlainText() or " ")
            probe.setTextWidth(max(80, self.viewport().width() - 8))
            height = max(34, math.ceil(probe.size().height()) + 2 * self.frameWidth() + 12)
            if self.height() != height:
                self.setFixedHeight(height)
        finally:
            self._fitting = False


class ViewTab(QWidget):
    status = Signal(str)
    questionsChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.setObjectName("viewPage")
        self.ctx = ctx
        self.document_id: Optional[str] = None
        self.q: Optional[Question] = None
        self._loading = False
        self._questions: list[Question] = []
        self._working_sources = []
        self._source_index = -1

        # left: document + pages
        self.doc_combo = QComboBox()
        self.doc_combo.setMinimumWidth(220)
        self.doc_combo.currentIndexChanged.connect(self._doc_changed)
        self.viewer = PageViewer(ctx.abs_path)
        self.viewer.pageChanged.connect(self._page_changed)
        self.page_info = QLabel()
        self.page_info.setWordWrap(True)
        left = QFrame()
        left.setObjectName("surface")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 10, 12, 10)
        ll.setSpacing(8)
        top = QHBoxLayout()
        source_title = QLabel("Source document")
        source_title.setObjectName("sectionTitle")
        top.addWidget(source_title)
        top.addWidget(self.doc_combo, 1)
        ll.addLayout(top)
        ll.addWidget(self.viewer, 1)
        self.page_info.setObjectName("pageInfo")
        ll.addWidget(self.page_info)

        # right: filter + list
        self.axis_filter = QComboBox()
        self.axis_filter.currentIndexChanged.connect(self._fill_list)
        self.qlist = QListWidget()
        self.qlist.setObjectName("reviewQuestionList")
        self.qlist.setMaximumHeight(100)
        self.qlist.currentItemChanged.connect(self._list_changed)
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Axis:"))
        fl.addWidget(self.axis_filter, 1)

        # right: editor
        self.header = QLabel()
        self.header.setObjectName("questionHeader")
        self.header.setTextFormat(Qt.RichText)
        self.question_edit = AutoHeightQuestionEdit()
        self.question_edit.setObjectName("questionText")
        self.axis_combo = QComboBox()
        for a in AXES:
            self.axis_combo.addItem(f"{a.code} — {a.name}", a.code)
            self.axis_combo.setItemData(self.axis_combo.count() - 1, a.definition, Qt.ToolTipRole)
        self.axis_combo.currentIndexChanged.connect(self._axis_changed)
        self.sub_axes = QListWidget()
        self.sub_axes.setFlow(QListWidget.LeftToRight)
        self.sub_axes.setWrapping(True)
        self.sub_axes.setFixedHeight(50)
        self.sub_axes.setGridSize(QSize(64, 19))
        self.sub_axes.setTextElideMode(Qt.ElideNone)
        for a in AXES:
            if a.code in ("B03", "B04"):
                continue
            it = QListWidgetItem(a.code)
            it.setToolTip(f"{a.name}: {a.definition}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, a.code)
            self.sub_axes.addItem(it)

        self.opt_group = QButtonGroup(self)
        self.opt_rows: dict[str, tuple[QRadioButton, QLineEdit]] = {}
        opt_box = QGroupBox("Options (the selected one is correct)")
        opt_box.setObjectName("reviewOptions")
        og = QGridLayout(opt_box)
        og.setContentsMargins(7, 10, 7, 5)
        og.setHorizontalSpacing(6)
        og.setVerticalSpacing(3)
        for i, lb in enumerate(MCQ5_LABELS):
            rb = QRadioButton(lb)
            text = QLineEdit()
            text.setFixedHeight(26)
            self.opt_group.addButton(rb)
            rb.toggled.connect(self._sync_answer)
            text.textEdited.connect(self._sync_answer)
            og.addWidget(rb, i, 0)
            og.addWidget(text, i, 1)
            self.opt_rows[lb] = (rb, text)
        self.answer = QLineEdit()
        self.answer.setReadOnly(True)
        self.answer.setFixedHeight(26)
        og.addWidget(QLabel("Answer"), 5, 0)
        og.addWidget(self.answer, 5, 1)
        self.evidence = QLineEdit()
        self.source_list = QListWidget()
        self.source_list.setFixedHeight(56)
        self.source_list.currentRowChanged.connect(self._source_selected)
        self.source_evidence = QPlainTextEdit()
        self.source_evidence.setFixedHeight(52)
        self.source_used_for = QLineEdit()
        self.reasoning = QPlainTextEdit()
        self.reasoning.setFixedHeight(62)
        self.rationale = QPlainTextEdit()
        self.rationale.setFixedHeight(40)

        form = QFormLayout()
        form.addRow("Question", self.question_edit)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        ed = QWidget()
        ed.setObjectName("reviewEditor")
        el = QVBoxLayout(ed)
        el.setContentsMargins(2, 2, 2, 2)
        el.setSpacing(4)
        el.addWidget(self.header)
        el.addLayout(form)
        el.addWidget(opt_box)
        f2 = QFormLayout()
        f2.setContentsMargins(0, 0, 0, 0)
        f2.setHorizontalSpacing(8)
        f2.setVerticalSpacing(4)
        self.reasoning.setToolTip("One reasoning step per line")
        self.source_list.setToolTip("Click a source page to display its image and evidence")
        f2.addRow("Reasoning steps", self.reasoning)
        f2.addRow("Source pages", self.source_list)
        f2.addRow("Selected evidence", self.source_evidence)
        f2.addRow("Used for", self.source_used_for)
        f2.addRow("Evidence summary", self.evidence)
        f2.addRow("Rationale", self.rationale)
        f2.addRow("Primary axis", self.axis_combo)
        f2.addRow("Sub-axes", self.sub_axes)
        el.addLayout(f2)
        el.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(ed)
        scroll.setFrameShape(QFrame.NoFrame)

        self.save_btn = QPushButton("Save")
        self.save_btn.setToolTip("Save and include this question in CSV/JSON/XLSX (Ctrl+S)")
        self.save_btn.clicked.connect(self.save)
        bl = QHBoxLayout()
        bl.addStretch(1)
        bl.addWidget(self.save_btn)

        right = QFrame()
        right.setObjectName("reviewPanel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(9, 8, 9, 8)
        rl.setSpacing(5)
        rl.addLayout(fl)
        rl.addWidget(self.qlist)
        rl.addWidget(scroll, 1)
        divider = QFrame()
        divider.setObjectName("separator")
        divider.setFrameShape(QFrame.HLine)
        rl.addWidget(divider)
        rl.addLayout(bl)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 5)
        split.setSizes([700, 700])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(split, 1)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save, context=Qt.WidgetWithChildrenShortcut)
        self._set_editor_enabled(False)
        self.reload_documents()

    # -- documents ----------------------------------------------------------
    def reload_documents(self) -> None:
        cur = self.document_id
        self.doc_combo.blockSignals(True)
        self.doc_combo.clear()
        counts = self.ctx.questions.counts_by_document()
        for d in self.ctx.documents.list():
            self.doc_combo.addItem(f"{d.document_id}  ({counts.get(d.document_id, 0)} questions)  "
                                   f"— {d.original_filename}", d.document_id)
        self.doc_combo.blockSignals(False)
        i = self.doc_combo.findData(cur) if cur else -1
        if i >= 0:
            self.doc_combo.setCurrentIndex(i)
            self._load_questions()
        elif self.doc_combo.count():
            self.doc_combo.setCurrentIndex(0)
            self._doc_changed(0)

    def open_document(self, document_id: str) -> None:
        i = self.doc_combo.findData(document_id)
        if i < 0:
            self.reload_documents()
            i = self.doc_combo.findData(document_id)
        if i >= 0:
            if self.doc_combo.currentIndex() == i:
                self._doc_changed(i)
            else:
                self.doc_combo.setCurrentIndex(i)

    def select_question(self, question_id: str) -> None:
        for i in range(self.qlist.count()):
            if self.qlist.item(i).data(Qt.UserRole) == question_id:
                self.qlist.setCurrentRow(i)
                return
        self.axis_filter.setCurrentIndex(0)
        for i in range(self.qlist.count()):
            if self.qlist.item(i).data(Qt.UserRole) == question_id:
                self.qlist.setCurrentRow(i)
                return

    def _doc_changed(self, i: int) -> None:
        doc_id = self.doc_combo.itemData(i)
        if not doc_id:
            return
        self.document_id = doc_id
        self.viewer.set_pages(self.ctx.pages.for_document(doc_id))
        self.q = None
        self._load_questions()

    def _load_questions(self) -> None:
        self._questions = self.ctx.questions.for_document(self.document_id) if self.document_id else []
        if self.viewer.current_page:
            self._page_changed(self.viewer.current_page.page_id)
        counts = Counter(q.primary_axis for q in self._questions)
        cur = self.axis_filter.currentData()
        self.axis_filter.blockSignals(True)
        self.axis_filter.clear()
        self.axis_filter.addItem(f"All ({len(self._questions)})", "all")
        for a in AXES:
            self.axis_filter.addItem(f"{a.code} — {a.name} ({counts.get(a.code, 0)})", a.code)
        i = self.axis_filter.findData(cur) if cur else 0
        self.axis_filter.setCurrentIndex(max(i, 0))
        self.axis_filter.blockSignals(False)
        self._fill_list()

    def _fill_list(self) -> None:
        flt = self.axis_filter.currentData() or "all"
        cur = self.q.question_id if self.q else None
        pages = {p.page_id: p.page_number for p in self.viewer.pages}
        self.qlist.blockSignals(True)
        self.qlist.clear()
        for q in self._questions:
            if flt != "all" and q.primary_axis != flt:
                continue
            mark = "[Saved, edited] " if q.reviewed and q.edited else "[Saved] " if q.reviewed else ""
            multi = f" ({len(q.source_pages)} pages)" if len(q.source_pages) > 1 else ""
            it = QListWidgetItem(f"p{pages.get(q.page_id, '?')}{multi}  [{q.primary_axis}]  {mark}{q.question_bn[:90]}")
            it.setData(Qt.UserRole, q.question_id)
            self.qlist.addItem(it)
            if q.question_id == cur:
                self.qlist.setCurrentItem(it)
        self.qlist.blockSignals(False)
        if self.qlist.currentItem() is None and self.qlist.count():
            self.qlist.setCurrentRow(0)
        elif not self.qlist.count():
            self.q = None
            self._set_editor_enabled(False)

    def _page_changed(self, page_id: str) -> None:
        """Say what Gemini judged the page to be, and why it has no questions if so."""
        page = self.ctx.pages.get(page_id)
        if page is None:
            self.page_info.clear()
            return
        n = sum(1 for q in self._questions if q.page_id == page_id)
        if page.status != "done":
            text = "Not processed yet." if page.status == "pending" else f"Failed: {page.error[:200]}"
        else:
            kind = page.content_type.replace("_", " ") or "page"
            text = f"{kind} · {n} question(s)" + (f" · {page.content_note}" if page.content_note else "")
            if n == 0:
                text = f"No questions on this page — {text}"
        self.page_info.setText(text)

    # -- editor -----------------------------------------------------------------
    def _set_editor_enabled(self, on: bool) -> None:
        for w in (self.question_edit, self.axis_combo, self.sub_axes, self.evidence, self.source_list,
                  self.source_evidence, self.source_used_for, self.reasoning, self.rationale, self.save_btn,
                  *[w for row in self.opt_rows.values() for w in row]):
            w.setEnabled(on)
        if not on:
            self.header.setText("<i>No questions yet. Process this document from the Library.</i>")

    def _list_changed(self, cur, _prev) -> None:
        if cur is None:
            return
        q = self.ctx.questions.get(cur.data(Qt.UserRole))
        if q:
            self._fill(q)

    def _fill(self, q: Question) -> None:
        self._loading = True
        try:
            self.q = q
            self._set_editor_enabled(True)
            page = self.ctx.pages.get(q.page_id)
            saved = " &nbsp; <span style='color:#63dfbc'>Saved for export</span>" if q.reviewed else " &nbsp; Draft · not in dataset files"
            edited = " &nbsp; <span style='color:#f3c779'>edited</span>" if q.edited else ""
            page_numbers = [str(self.ctx.pages.get(s.page_id).page_number) for s in q.source_pages]
            label = "pages " + ", ".join(page_numbers) if len(page_numbers) > 1 else f"page {page_numbers[0]}"
            warning = " &nbsp; <span style='color:#f3c779'>Check B03 absence across source pages</span>" if q.primary_axis == "B03" and len(page_numbers) > 1 else ""
            self.header.setText(f"<b>{q.question_id}</b> &nbsp; {label}{saved}{edited}{warning}")
            self.question_edit.setPlainText(q.question_bn)
            self.axis_combo.setCurrentIndex(max(self.axis_combo.findData(q.primary_axis), 0))
            for k in range(self.sub_axes.count()):
                it = self.sub_axes.item(k)
                it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in q.sub_axes else Qt.Unchecked)
            self._fill_options(q.question_format, q.option_map(), q.correct_option)
            self.evidence.setText(q.evidence_snippet)
            self.evidence.setReadOnly(bool(q.import_key))
            self.evidence.setToolTip("Built from the source-page evidence above" if q.import_key else "Evidence summary")
            self._working_sources = copy.deepcopy(q.source_pages)
            self._source_index = -1
            self.source_list.blockSignals(True)
            self.source_list.clear()
            for source in self._working_sources:
                source_page = self.ctx.pages.get(source.page_id)
                self.source_list.addItem(f"Page {source_page.page_number if source_page else '?'} · {source.used_for[:80]}")
            self.source_list.blockSignals(False)
            if self._working_sources:
                self.source_list.setCurrentRow(0)
                self._load_source_editor(0)
            self.reasoning.setPlainText("\n".join(q.reasoning_steps))
            self.rationale.setPlainText(q.rationale)
        finally:
            self._loading = False
        self.viewer.show_page_id(q.page_id)

    def _store_source_editor(self) -> None:
        if 0 <= self._source_index < len(self._working_sources):
            source = self._working_sources[self._source_index]
            source.evidence_snippet = self.source_evidence.toPlainText().strip()
            source.used_for = self.source_used_for.text().strip()

    def _load_source_editor(self, index: int) -> None:
        self._source_index = index
        if 0 <= index < len(self._working_sources):
            source = self._working_sources[index]
            self.source_evidence.setPlainText(source.evidence_snippet)
            self.source_used_for.setText(source.used_for)
            self.viewer.show_page_id(source.page_id)

    def _source_selected(self, index: int) -> None:
        if self._loading:
            return
        self._store_source_editor()
        self._load_source_editor(index)

    def _fill_options(self, fmt: str, omap: dict[str, str], correct: str) -> None:
        verify = fmt == FORMAT_VERIFY3
        self.opt_group.setExclusive(False)
        for lb, (rb, text) in self.opt_rows.items():
            visible = not verify or lb in VERIFY3_LABELS
            rb.setVisible(visible)
            text.setVisible(visible)
            text.setReadOnly(verify)
            text.setText(omap.get(lb, ""))
            rb.setChecked(lb == correct)
        self.opt_group.setExclusive(True)
        self._sync_answer()

    def _axis_changed(self) -> None:
        if self._loading or not self.q:
            return
        new_fmt = expected_format(self.axis_combo.currentData())
        if new_fmt == FORMAT_VERIFY3:
            self._fill_options(new_fmt, dict(VERIFY3_OPTIONS), "")
        elif self.q.question_format == FORMAT_VERIFY3 and new_fmt != FORMAT_VERIFY3:
            self._fill_options(new_fmt, {}, "")  # claim -> ordinary: options must be written

    def _sync_answer(self, *_):
        for rb, text in self.opt_rows.values():
            if rb.isChecked():
                self.answer.setText(text.text().strip())
                return
        self.answer.setText("")

    def _form_question(self) -> Question:
        self._store_source_editor()
        q = copy.deepcopy(self.q)
        q.question_bn = normalize_answer(self.question_edit.toPlainText())
        q.primary_axis = self.axis_combo.currentData()
        q.question_format = expected_format(q.primary_axis)
        q.question_type = expected_type(q.primary_axis)
        q.sub_axes = [self.sub_axes.item(k).data(Qt.UserRole) for k in range(self.sub_axes.count())
                      if self.sub_axes.item(k).checkState() == Qt.Checked and
                      self.sub_axes.item(k).data(Qt.UserRole) != q.primary_axis]
        q.options, q.correct_option = [], ""
        for lb in labels_for(q.question_format):
            rb, text = self.opt_rows[lb]
            q.options.append(Option(lb, normalize_answer(text.text())))
            if rb.isChecked():
                q.correct_option = lb
        q.answer_bn = q.option_text(q.correct_option)
        q.source_pages = copy.deepcopy(self._working_sources)
        q.reasoning_steps = [s.strip() for s in self.reasoning.toPlainText().splitlines() if s.strip()]
        q.evidence_snippet = normalize_answer(self.evidence.text())
        if q.import_key:
            q.evidence_snippet = " | ".join(f"{s.page_id}: {s.evidence_snippet}" for s in q.source_pages)
        elif len(q.source_pages) == 1:
            q.source_pages[0].evidence_snippet = q.evidence_snippet
        q.rationale = self.rationale.toPlainText().strip()
        return q

    def save(self) -> None:
        if not self.q:
            return
        q = self._form_question()
        texts = [o.text for o in q.options]
        problem = ("the question is empty" if not q.question_bn else
                   "every option needs text" if any(not t for t in texts) else
                   "two options are identical" if len(set(texts)) != len(texts) else
                   "select the correct option" if not q.correct_option else
                   "B03 answer must be the abstention text" if q.primary_axis == "B03" and q.answer_bn != ABSTAIN_TEXT else
                   "B04 options must remain fixed" if q.primary_axis == "B04" and q.option_map() != VERIFY3_OPTIONS else
                   "source evidence is empty" if q.import_key and any(not s.evidence_snippet for s in q.source_pages) else "")
        if problem:
            QMessageBox.warning(self, "Cannot save", f"Not saved: {problem}.")
            return
        self.q = self.ctx.questions.save_edit(q)
        try:
            self.ctx.portable.sync()
            self.status.emit(f"Saved {q.question_id}; included in dataset files.")
        except Exception as exc:
            self.ctx.db.last_mirror_error = str(exc)
            QMessageBox.warning(self, "Dataset files", f"Question saved in the app, but CSV/JSON sync failed:\n{exc}")
        self._load_questions()
        self.questionsChanged.emit()

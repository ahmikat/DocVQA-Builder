"""View tab: browse a document's pages and edit its generated questions."""
from __future__ import annotations

import copy
from collections import Counter
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ..models.records import Option, Question
from ..models.taxonomy import (AXES, FORMAT_VERIFY3, MCQ5_LABELS, VERIFY3_LABELS, VERIFY3_OPTIONS, expected_format,
                               expected_type, labels_for)
from ..models.text import normalize_answer
from ..services.context import AppContext
from .page_viewer import PageViewer


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
        self.qlist.setMaximumHeight(125)
        self.qlist.currentItemChanged.connect(self._list_changed)
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Axis:"))
        fl.addWidget(self.axis_filter, 1)

        # right: editor
        self.header = QLabel()
        self.header.setObjectName("questionHeader")
        self.header.setTextFormat(Qt.RichText)
        self.question_edit = QPlainTextEdit()
        self.question_edit.setObjectName("questionText")
        self.question_edit.setFixedHeight(62)
        self.axis_combo = QComboBox()
        for a in AXES:
            self.axis_combo.addItem(f"{a.code} — {a.name}", a.code)
            self.axis_combo.setItemData(self.axis_combo.count() - 1, a.definition, Qt.ToolTipRole)
        self.axis_combo.currentIndexChanged.connect(self._axis_changed)
        self.sub_axes = QListWidget()
        self.sub_axes.setFlow(QListWidget.LeftToRight)
        self.sub_axes.setWrapping(True)
        self.sub_axes.setFixedHeight(68)
        self.sub_axes.setGridSize(QSize(70, 22))
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
        og = QGridLayout(opt_box)
        for i, lb in enumerate(MCQ5_LABELS):
            rb = QRadioButton(lb)
            text = QLineEdit()
            self.opt_group.addButton(rb)
            rb.toggled.connect(self._sync_answer)
            text.textEdited.connect(self._sync_answer)
            og.addWidget(rb, i, 0)
            og.addWidget(text, i, 1)
            self.opt_rows[lb] = (rb, text)
        self.answer = QLineEdit()
        self.answer.setReadOnly(True)
        og.addWidget(QLabel("Answer"), 5, 0)
        og.addWidget(self.answer, 5, 1)
        self.evidence = QLineEdit()
        self.rationale = QPlainTextEdit()
        self.rationale.setFixedHeight(48)

        form = QFormLayout()
        form.addRow("Question", self.question_edit)
        form.addRow("Primary axis", self.axis_combo)
        form.addRow("Sub-axes", self.sub_axes)
        ed = QWidget()
        el = QVBoxLayout(ed)
        el.addWidget(self.header)
        el.addLayout(form)
        el.addWidget(opt_box)
        f2 = QFormLayout()
        f2.addRow("Evidence", self.evidence)
        f2.addRow("Rationale", self.rationale)
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
        right.setObjectName("surface")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(8)
        review_title = QLabel("Question review")
        review_title.setObjectName("sectionTitle")
        review_hint = QLabel("Check the page, answer and evidence. Save a question to include it in dataset files.")
        review_hint.setObjectName("sectionHint")
        review_hint.setWordWrap(True)
        rl.addWidget(review_title)
        rl.addWidget(review_hint)
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
        hero = QFrame()
        hero.setObjectName("hero")
        hero_lay = QHBoxLayout(hero)
        hero_lay.setContentsMargins(16, 11, 16, 11)
        hero_lay.setSpacing(20)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        eyebrow = QLabel("REVIEW WORKSPACE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Review questions")
        title.setObjectName("pageTitle")
        heading.addWidget(eyebrow)
        heading.addWidget(title)
        hero_lay.addLayout(heading)
        hero_lay.addStretch(1)
        self.review_summary = QLabel("0 saved / 0 generated")
        self.review_summary.setObjectName("reviewSummary")
        hero_lay.addWidget(self.review_summary)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 11)
        column = QVBoxLayout()
        column.setSpacing(9)
        column.addWidget(hero)
        column.addWidget(split, 1)
        lay.addLayout(column)
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
        saved = sum(q.reviewed for q in self._questions)
        self.review_summary.setText(f"{saved} saved / {len(self._questions)} generated")
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
            it = QListWidgetItem(f"p{pages.get(q.page_id, '?')}  [{q.primary_axis}]  {mark}{q.question_bn[:90]}")
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
        for w in (self.question_edit, self.axis_combo, self.sub_axes, self.evidence, self.rationale, self.save_btn,
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
            self.header.setText(f"<b>{q.question_id}</b> &nbsp; page {page.page_number if page else '?'}{saved}{edited}")
            self.question_edit.setPlainText(q.question_bn)
            self.axis_combo.setCurrentIndex(max(self.axis_combo.findData(q.primary_axis), 0))
            for k in range(self.sub_axes.count()):
                it = self.sub_axes.item(k)
                it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in q.sub_axes else Qt.Unchecked)
            self._fill_options(q.question_format, q.option_map(), q.correct_option)
            self.evidence.setText(q.evidence_snippet)
            self.rationale.setPlainText(q.rationale)
        finally:
            self._loading = False
        self.viewer.show_page_id(q.page_id)

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
        q.evidence_snippet = normalize_answer(self.evidence.text())
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
                   "select the correct option" if not q.correct_option else "")
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

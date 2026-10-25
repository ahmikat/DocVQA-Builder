"""Page viewer: thumbnails, zoom and view-only rotation."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QToolBar, QVBoxLayout, QWidget)

from ..models.records import Page


class _View(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#26364a")))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
        else:
            super().wheelEvent(e)


class PageViewer(QWidget):
    """Shows the pages of one document. Rotation affects the view only."""

    pageChanged = Signal(str)  # page_id

    def __init__(self, resolve_path, parent=None):
        super().__init__(parent)
        self._resolve = resolve_path
        self.pages: list[Page] = []
        self.index = -1
        self._rotation = 0
        self._pix_item: Optional[QGraphicsPixmapItem] = None

        self.scene = QGraphicsScene(self)
        self.view = _View()
        self.view.setScene(self.scene)

        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setIconSize(QSize(80, 108))
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.setFixedWidth(108)
        self.thumbs.setSpacing(7)
        self.thumbs.currentRowChanged.connect(self.show_index)

        tb = QToolBar()
        self.lbl = QLabel(" — ")
        for text, tip, fn, key in (("Prev", "Previous page (PgUp)", self.prev_page, "PgUp"),
                                   ("Next", "Next page (PgDown)", self.next_page, "PgDown"),
                                   ("−", "Zoom out (Ctrl+-)", lambda: self.view.scale(1 / 1.2, 1 / 1.2), "Ctrl+-"),
                                   ("+", "Zoom in (Ctrl+=)", lambda: self.view.scale(1.2, 1.2), "Ctrl+="),
                                   ("Fit", "Fit page (Ctrl+0)", self.fit, "Ctrl+0"),
                                   ("100%", "Actual size", self.actual_size, None),
                                   ("Rotate", "Rotate view 90° (the stored image is not changed)", self.rotate, None)):
            a = QAction(text, self)
            a.setToolTip(tip)
            a.triggered.connect(fn)
            if key:
                a.setShortcut(key)
                a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            tb.addAction(a)
        tb.addSeparator()
        tb.addWidget(self.lbl)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(tb)
        rl.addWidget(self.view, 1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.thumbs)
        lay.addWidget(right, 1)

    def set_pages(self, pages: list[Page]) -> None:
        self.pages = pages
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for p in pages:
            pix = QPixmap(str(self._resolve(p.image_path)))
            icon = QIcon(pix.scaled(80, 108, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not pix.isNull() else QIcon()
            it = QListWidgetItem(icon, str(p.page_number))
            it.setToolTip(p.page_id)
            self.thumbs.addItem(it)
        self.thumbs.blockSignals(False)
        self.index = -1
        if pages:
            self.show_index(0)
        else:
            self.scene.clear()
            self._pix_item = None
            self.lbl.setText(" no pages ")

    def show_page_id(self, page_id: str) -> None:
        for i, p in enumerate(self.pages):
            if p.page_id == page_id:
                self.show_index(i)
                return

    def show_index(self, i: int) -> None:
        if not (0 <= i < len(self.pages)) or i == self.index:
            return
        self.index = i
        p = self.pages[i]
        self.scene.clear()
        pix = QPixmap(str(self._resolve(p.image_path)))
        self._pix_item = self.scene.addPixmap(pix)
        self.scene.setSceneRect(QRectF(pix.rect()))
        self._apply_rotation()
        self.fit()
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(i)
        self.thumbs.blockSignals(False)
        self.lbl.setText(f" Page {p.page_number}/{len(self.pages)} ")
        self.pageChanged.emit(p.page_id)

    @property
    def current_page(self) -> Optional[Page]:
        return self.pages[self.index] if 0 <= self.index < len(self.pages) else None

    def next_page(self):
        self.show_index(self.index + 1)

    def prev_page(self):
        self.show_index(self.index - 1)

    def fit(self):
        if self._pix_item:
            self.view.fitInView(self._pix_item, Qt.KeepAspectRatio)

    def actual_size(self):
        self.view.setTransform(QTransform())

    def rotate(self):
        self._rotation = (self._rotation + 90) % 360
        self._apply_rotation()
        self.fit()

    def _apply_rotation(self):
        if self._pix_item:
            self._pix_item.setTransformOriginPoint(self._pix_item.boundingRect().center())
            self._pix_item.setRotation(self._rotation)

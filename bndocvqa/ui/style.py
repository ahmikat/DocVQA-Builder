"""A restrained dark theme shared by the library, reviewer, and dialogs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QWidget


BUTTON_ROLES: dict[str, str] = {
    "Import files…": "primary", "Export ZIP…": "primary", "Save": "primary",
    "Add": "primary", "Test selected": "primary", "OK": "primary", "&OK": "primary",
    "Yes": "primary", "&Yes": "primary", "Open index.html": "primary",
    "Generate questions": "success", "Gemini API keys…": "ai",
    "Select all": "quiet", "Clear": "quiet", "Remove…": "danger", "Remove": "danger",
}

_ICON_DIR = Path(__file__).with_name("icons").as_posix()

_ROLE_COLORS = {
    "primary": ("#4f83f1", "#6999fa", "#3c6fd8", "#ffffff", "#78a4ff"),
    "success": ("#168a73", "#1da187", "#116d5c", "#ffffff", "#39bb9d"),
    "ai": ("#654ac1", "#7960d4", "#553ca6", "#ffffff", "#9b87eb"),
    "danger": ("#34232d", "#4b2b36", "#622c3a", "#ffb4c1", "#82505c"),
    "quiet": ("#192638", "#23364e", "#122033", "#b9c9df", "#344a63"),
}


def _button_css() -> str:
    blocks = ["""
QPushButton {
    min-height: 28px; padding: 2px 10px;
    border: 1px solid #354960; border-radius: 7px;
    background: #1d2b3e; color: #e3edfa; font-weight: 600;
}
QPushButton:hover { background: #283b53; border-color: #6080a6; }
QPushButton:pressed { background: #152437; }
QPushButton:disabled { background: #192433; color: #75849b; border-color: #273548; }
QPushButton:focus { border: 1px solid #93b6ff; }
"""]
    for role, (normal, hover, pressed, text, border) in _ROLE_COLORS.items():
        blocks.append(f"""
QPushButton[role="{role}"] {{ background: {normal}; color: {text}; border-color: {border}; }}
QPushButton[role="{role}"]:hover {{ background: {hover}; }}
QPushButton[role="{role}"]:pressed {{ background: {pressed}; }}
QPushButton[role="{role}"]:disabled {{ background: #192433; color: #75849b; border-color: #273548; }}
""")
    return "".join(blocks)


_CONTROLS_CSS = f"""
QWidget {{ color: #e6edf7; font-size: 10.5pt; }}
QMainWindow, QDialog, QMessageBox {{ background: #0e1725; }}
QWidget#libraryPage, QWidget#viewPage {{ background: #0e1725; }}
QLabel {{ background: transparent; }}
QLabel#eyebrow {{ color: #69aaf8; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#pageTitle {{ color: #f3f7ff; font-size: 18pt; font-weight: 700; }}
QLabel#muted, QLabel#helper, QLabel#sectionHint {{ color: #9fb0c8; }}
QLabel#sectionTitle {{ color: #edf4ff; font-size: 11pt; font-weight: 700; }}
QLabel#metricLabel {{ color: #aabbd1; font-size: 9.5pt; }}
QLabel#metricValue {{ color: #f5f8ff; font-size: 17pt; font-weight: 700; }}
QLabel#emptyState {{ color: #aabbd1; font-size: 12pt; padding: 44px; }}
QLabel#reviewSummary {{ color: #a7d6ca; font-weight: 600; }}
QLabel#pageInfo {{ color: #b9c9dd; padding: 4px 2px; }}
QLabel#questionHeader {{ color: #ecf4ff; font-size: 11pt; }}
QLabel#questionText {{ font-size: 12.5pt; }}

QFrame#surface, QFrame#toolbarSurface, QFrame#metricCard {{
    background: #152234; border: 1px solid #283a50; border-radius: 11px;
}}
QFrame#metricCard {{ background: #18283b; }}
QFrame#hero {{ background: #14243a; border: 1px solid #2b4664; border-radius: 12px; }}
QFrame#separator {{ background: #2a3b50; max-height: 1px; border: none; }}

QTabWidget::pane {{ border: none; background: #0e1725; }}
QTabBar {{ background: #0b1421; }}
QTabBar::tab {{
    min-width: 86px; padding: 8px 18px; margin: 6px 3px 0 6px;
    border: 1px solid #27394e; border-bottom: none;
    border-top-left-radius: 9px; border-top-right-radius: 9px;
    background: #142235; color: #a9bdd7;
}}
QTabBar::tab:hover {{ background: #1d3049; color: #e3edfa; }}
QTabBar::tab:selected {{ background: #233b5a; color: #ffffff; border-color: #537eb2; font-weight: 700; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #101c2b; color: #eaf1fb; selection-background-color: #426cae;
    border: 1px solid #34465d; border-radius: 7px; padding: 5px 9px;
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover {{ border-color: #537198; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: #78a8f7; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{ color: #79899e; background: #172233; }}
QLineEdit[readOnly="true"] {{ color: #a8bdd8; background: #172538; }}
QPlainTextEdit#questionText {{ font-size: 12.5pt; line-height: 1.3; }}
QComboBox {{ min-height: 20px; padding-right: 24px; }}
QComboBox::drop-down {{ border: none; width: 25px; }}
QComboBox::down-arrow {{ image: url({_ICON_DIR}/down.svg); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: #17273b; color: #e7effb; selection-background-color: #355b93; }}
QToolTip {{ background: #24364d; color: #f0f6ff; border: 1px solid #58749a; padding: 5px; }}

QGroupBox {{
    background: #17263a; border: 1px solid #2d425b; border-radius: 10px;
    margin-top: 13px; padding: 11px 8px 6px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #cfe0fa; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QTableWidget, QListWidget {{
    background: #121f30; alternate-background-color: #17263a;
    border: 1px solid #283a50; border-radius: 9px;
    color: #e7effa; outline: none;
    selection-background-color: #294c78; selection-color: #ffffff;
}}
QTableWidget::item {{ padding: 5px 7px; border-bottom: 1px solid #233449; }}
QListWidget::item {{ padding: 4px 6px; border-radius: 5px; }}
QTableWidget::item:hover, QListWidget::item:hover {{ background: #23364d; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: #2c527f; color: #ffffff; }}
QHeaderView::section {{
    background: #1d2c40; color: #bdd0e8; padding: 7px 9px;
    border: none; border-right: 1px solid #2c3e54; border-bottom: 1px solid #3b5270;
    font-weight: 700;
}}
QHeaderView::section:hover {{ background: #263c57; }}

QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QListWidget::indicator, QTableView::indicator {{
    width: 16px; height: 16px; border: 1px solid #6d85a3;
    border-radius: 4px; background: #101c2b;
}}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTableView::indicator:checked {{
    background: #4f83f1; border-color: #78a4ff; image: url({_ICON_DIR}/check.svg);
}}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid #6d85a3;
    border-radius: 9px; background: #101c2b; }}
QRadioButton::indicator:checked {{ background: #4f83f1; border: 4px solid #79a6f7; }}

QToolBar {{ background: transparent; border: none; spacing: 4px; }}
QToolButton {{
    min-width: 24px; min-height: 24px; padding: 2px 6px; margin: 1px;
    border: 1px solid #354a63; border-radius: 7px;
    background: #203149; color: #d9e8fb;
}}
QToolButton:hover {{ background: #2d4663; border-color: #6a90bf; }}
QToolButton:pressed {{ background: #17283c; }}
QToolButton:checked {{ background: #355d87; }}
QSplitter::handle {{ background: #263a52; width: 5px; height: 5px; }}
QSplitter::handle:hover {{ background: #4f83f1; }}
QGraphicsView {{ border: 1px solid #30435a; border-radius: 8px; }}

QScrollBar:vertical {{ width: 11px; background: #111d2c; }}
QScrollBar:horizontal {{ height: 11px; background: #111d2c; }}
QScrollBar::handle {{ background: #3c526e; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #55749b; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{ background: #0b1421; color: #aebfd6; border-top: 1px solid #27384d; padding: 3px 8px; }}
QStatusBar::item {{ border: none; }}
QMenuBar, QMenu {{ background: #152439; color: #e6edf7; }}
QMenu::item:selected, QMenuBar::item:selected {{ background: #31547f; }}
QMenu::item {{ padding: 6px 22px; }}
QProgressBar {{ background: #152439; border: 1px solid #34465d; border-radius: 6px; text-align: center; }}
QProgressBar::chunk {{ background: #4f83f1; border-radius: 5px; }}
"""

STYLE = _CONTROLS_CSS + _button_css()


def set_role(button: QPushButton, role: str | None) -> None:
    button.setProperty("role", role or "")
    button.style().unpolish(button)
    button.style().polish(button)


def apply_button_roles(root: QWidget) -> None:
    for button in root.findChildren(QPushButton):
        role = BUTTON_ROLES.get(button.text())
        if role:
            set_role(button, role)


class DialogButtonColorer(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, (QDialog, QMessageBox)):
            apply_button_roles(obj)
        return False


def install(app) -> None:
    """Set one palette for all native Qt surfaces, then apply control details."""
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.Window: "#0e1725", QPalette.WindowText: "#e6edf7",
        QPalette.Base: "#121f30", QPalette.AlternateBase: "#17263a",
        QPalette.Text: "#e6edf7", QPalette.Button: "#1d2b3e",
        QPalette.ButtonText: "#e6edf7", QPalette.Highlight: "#315c94",
        QPalette.HighlightedText: "#ffffff", QPalette.ToolTipBase: "#24364d",
        QPalette.ToolTipText: "#f0f6ff",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    colorer = DialogButtonColorer(app)
    app.installEventFilter(colorer)
    app._dialog_button_colorer = colorer

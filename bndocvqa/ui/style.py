"""Application stylesheet and button colour roles.

Each button gets a `role` property based on what it does, and the stylesheet
colours buttons by role:
  primary  (blue)    main actions: import, view, export, save, OK
  success  (green)   process
  warning  (amber)   selection helpers
  danger   (red)     remove
  ai       (purple)  Gemini keys and model
  (none)   (indigo tint) secondary tools and navigation

Every other clickable control (tabs, menus, toolbar buttons, dropdowns,
checkboxes, radio buttons, list/table selection, headers) is coloured too.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QWidget

BUTTON_ROLES: dict[str, str] = {
    # primary
    "Save": "primary", "Import files…": "primary", "Import folder…": "primary", "View": "primary",
    "Export…": "primary", "Add": "primary", "Test selected": "primary", "Paste": "primary",
    "OK": "primary", "&OK": "primary", "Yes": "primary", "&Yes": "primary", "Open index.html": "primary",
    # success
    "▶ Process": "success",
    # warning
    "Select all": "warning", "Clear": "warning",
    # danger
    "Remove…": "danger", "Remove": "danger",
    # Gemini
    "Gemini API keys…": "ai",
}

_ROLE_COLORS = {
    # role: (background, hover, pressed, text, border)
    "primary": ("#2563eb", "#1d4ed8", "#1e40af", "#ffffff", "#1d4ed8"),
    "success": ("#16a34a", "#15803d", "#166534", "#ffffff", "#15803d"),
    "warning": ("#fef3c7", "#fde68a", "#fcd34d", "#92400e", "#f59e0b"),
    "danger": ("#fee2e2", "#fecaca", "#fca5a5", "#991b1b", "#f87171"),
    "ai": ("#7c3aed", "#6d28d9", "#5b21b6", "#ffffff", "#6d28d9"),
}

_ICON_DIR = (Path(__file__).with_name("icons")).as_posix()

BLUE = "#2563eb"
BLUE_SOFT = "#dbeafe"
INDIGO_SOFT = "#e0e7ff"
INDIGO_TEXT = "#3730a3"
TEAL_SOFT = "#ccfbf1"
TEAL_TEXT = "#115e59"


def _button_css() -> str:
    css = [f"""
QPushButton {{
    padding: 4px 12px; border: 1px solid #a5b4fc; border-radius: 4px;
    background: {INDIGO_SOFT}; color: {INDIGO_TEXT};
}}
QPushButton:hover {{ background: #c7d2fe; }}
QPushButton:pressed {{ background: #a5b4fc; }}
QPushButton:disabled {{ background: #f3f4f6; color: #9ca3af; border-color: #e5e7eb; }}
QPushButton:focus {{ outline: none; border: 2px solid {BLUE}; }}
QPushButton::menu-indicator {{ subcontrol-position: right center; right: 6px; }}
"""]
    for role, (bg, hover, pressed, fg, border) in _ROLE_COLORS.items():
        css.append(f"""
QPushButton[role="{role}"] {{ background: {bg}; color: {fg}; border-color: {border}; font-weight: 600; }}
QPushButton[role="{role}"]:hover {{ background: {hover}; }}
QPushButton[role="{role}"]:pressed {{ background: {pressed}; }}
QPushButton[role="{role}"]:disabled {{ background: #e5e7eb; color: #9ca3af; border-color: #e5e7eb; }}
""")
    return "".join(css)


_CONTROLS_CSS = f"""
QWidget {{ font-size: 10.5pt; }}
QPlainTextEdit#questionText, QLabel#questionText {{ font-size: 12.5pt; }}
QGroupBox {{ font-weight: 600; margin-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 6px; padding: 0 3px; color: {INDIGO_TEXT}; }}

/* Tabs */
QTabBar::tab {{
    padding: 6px 14px; margin-right: 2px; border: 1px solid #93c5fd; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px; background: {BLUE_SOFT}; color: #1e3a8a;
}}
QTabBar::tab:hover {{ background: #bfdbfe; }}
QTabBar::tab:selected {{ background: {BLUE}; color: white; font-weight: 600; }}

/* Menus */
QMenuBar {{ background: #eef2ff; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; color: {INDIGO_TEXT}; }}
QMenuBar::item:selected {{ background: #c7d2fe; border-radius: 3px; }}
QMenu {{ background: white; border: 1px solid #a5b4fc; }}
QMenu::item {{ padding: 5px 22px; color: #1f2937; }}
QMenu::item:selected {{ background: #7c3aed; color: white; }}

/* Toolbar buttons (page viewer) */
QToolButton {{
    padding: 3px 8px; margin: 1px; border: 1px solid #5eead4; border-radius: 4px;
    background: {TEAL_SOFT}; color: {TEAL_TEXT}; font-weight: 600;
}}
QToolButton:hover {{ background: #99f6e4; }}
QToolButton:pressed {{ background: #5eead4; }}
QToolButton:checked {{ background: #f59e0b; color: white; border-color: #d97706; }}

/* Dropdowns */
QComboBox {{
    padding: 3px 8px; border: 1px solid #93c5fd; border-radius: 4px; background: #eff6ff; color: #1e3a8a;
}}
QComboBox:hover {{ border-color: {BLUE}; background: {BLUE_SOFT}; }}
QComboBox::drop-down {{ border-left: 1px solid #93c5fd; width: 20px; background: {BLUE_SOFT};
    border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
QComboBox::down-arrow {{ image: url({_ICON_DIR}/down.svg); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ selection-background-color: {BLUE}; selection-color: white; }}

/* Spin boxes */
QSpinBox, QDoubleSpinBox {{ padding: 2px 6px; border: 1px solid #93c5fd; border-radius: 4px; background: #eff6ff; }}

/* Checkboxes and radio buttons */
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 2px solid {BLUE}; background: white; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ background: {BLUE_SOFT}; }}
QCheckBox::indicator:checked {{ background: {BLUE}; }}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                stop:0 #16a34a, stop:0.55 #16a34a, stop:0.6 white, stop:1 white);
    border-color: #16a34a;
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: #d1d5db; background: #f3f4f6; }}
QListWidget::indicator {{ width: 13px; height: 13px; border: 2px solid {BLUE}; border-radius: 3px; background: white; }}
QListWidget::indicator:checked {{ background: {BLUE}; }}

/* Lists and tables */
QListWidget::item:hover, QTableView::item:hover, QTableWidget::item:hover {{ background: {BLUE_SOFT}; }}
QListWidget::item:selected, QTableView::item:selected, QTableWidget::item:selected {{
    background: {BLUE}; color: white;
}}
QHeaderView::section {{
    background: {INDIGO_SOFT}; color: {INDIGO_TEXT}; padding: 4px 6px; border: none;
    border-right: 1px solid #c7d2fe; border-bottom: 1px solid #a5b4fc; font-weight: 600;
}}
QHeaderView::section:hover {{ background: #c7d2fe; }}

/* Links in rich text (Quality tab) use the palette link colour; scrollbars */
QScrollBar:vertical {{ width: 12px; background: #f1f5f9; }}
QScrollBar:horizontal {{ height: 12px; background: #f1f5f9; }}
QScrollBar::handle {{ background: #a5b4fc; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #818cf8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: #c7d2fe; }}
QSplitter::handle:hover {{ background: #818cf8; }}
"""

STYLE = _CONTROLS_CSS + _button_css()


def set_role(button: QPushButton, role: str | None) -> None:
    """Assign a colour role and re-polish so the change shows immediately."""
    button.setProperty("role", role or "")
    button.style().unpolish(button)
    button.style().polish(button)


def apply_button_roles(root: QWidget) -> None:
    """Colour every button under `root` according to BUTTON_ROLES."""
    for b in root.findChildren(QPushButton):
        role = BUTTON_ROLES.get(b.text())
        if role:
            set_role(b, role)


class DialogButtonColorer(QObject):
    """Application-wide event filter that colours buttons of dialogs as they open."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, (QDialog, QMessageBox)):
            apply_button_roles(obj)
        return False


def install(app) -> None:
    """Apply the stylesheet and colour dialog buttons app-wide."""
    app.setStyleSheet(STYLE)
    colorer = DialogButtonColorer(app)
    app.installEventFilter(colorer)
    app._dialog_button_colorer = colorer  # keep a reference

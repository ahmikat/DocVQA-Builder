"""GUI entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from .style import STYLE, install

BANGLA_FONTS = ["Noto Sans Bengali", "Hind Siliguri", "Nirmala UI", "Kalpurush", "SolaimanLipi", "Vrinda"]
BANGLA_FONT_FILES = [str(Path(__file__).with_name("fonts") / "NotoSansBengali-Regular.ttf"),
                     "C:/Windows/Fonts/Nirmala.ttc", "C:/Windows/Fonts/vrinda.ttf",
                     "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
                     "/System/Library/Fonts/Supplemental/Bangla MN.ttc"]


def app_font():
    """UI font with explicit Bangla fallbacks.

    An explicit family list makes Bangla render even where the platform does
    no automatic glyph fallback; the first installed Bangla font wins.
    """
    from PySide6.QtGui import QFont, QFontDatabase
    available = set(QFontDatabase.families())
    if not available & set(BANGLA_FONTS):
        # Some Qt backends skip font collections (.ttc); register known files directly.
        for path in BANGLA_FONT_FILES:
            if Path(path).is_file():
                available.update(QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(path)))
    bangla = [f for f in BANGLA_FONTS if f in available] or BANGLA_FONTS
    f = QFont()
    f.setFamilies(["Segoe UI", *bangla])
    f.setPointSizeF(10.5)
    return f


def run(data_dir=None) -> int:
    from PySide6.QtWidgets import QApplication

    from ..services.context import open_context
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Bangla DocVQA Builder")
    app.setFont(app_font())
    install(app)
    ctx = open_context(data_dir)
    win = MainWindow(ctx)
    win.show()
    return app.exec()

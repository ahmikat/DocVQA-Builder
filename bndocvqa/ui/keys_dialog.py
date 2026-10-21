"""Manage Gemini API keys from the UI (stored in the OS credential store)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..config.keystore import KeyStore
from ..services.context import AppContext


def _mask(secret: str) -> str:
    return f"…{secret[-4:]}" if len(secret) >= 8 else "…"


def test_key(api_key: str, model: str, timeout_s: int = 20) -> str:
    """Check that a key works and can see `model`. Uses no generation quota."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_s * 1000))
    m = client.models.get(model=model)
    return getattr(m, "display_name", None) or getattr(m, "name", model)


class GeminiKeysDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.store = KeyStore()
        self.setWindowTitle("Gemini API keys and model")
        self.resize(720, 480)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Google Cloud project", "Key", "Stored in"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        add_box = QGroupBox("Add a key")
        f = QFormLayout(add_box)
        self.label = QLineEdit()
        self.label.setPlaceholderText("e.g. key1")
        self.project = QLineEdit()
        self.project.setPlaceholderText("Google Cloud project — leave empty if this key has its own project")
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        self.secret.setPlaceholderText("paste the API key (AIza…)")
        paste = QPushButton("Paste")
        paste.clicked.connect(lambda: self.secret.setText(QGuiApplication.clipboard().text().strip()))
        row = QHBoxLayout()
        row.addWidget(self.secret, 1)
        row.addWidget(paste)
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        f.addRow("Name", self.label)
        f.addRow("Project", self.project)
        f.addRow("API key", row)
        f.addRow("", add)

        test = QPushButton("Test selected")
        test.clicked.connect(self._test)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        acts = QHBoxLayout()
        acts.addWidget(test)
        acts.addWidget(remove)
        acts.addStretch(1)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(list(dict.fromkeys([ctx.settings.gemini_model, *ctx.settings.gemini_model_limits])))
        self.model.setCurrentText(ctx.settings.gemini_model)
        limits = ", ".join(f"{m}: {rpm or ctx.settings.gemini_default_rpm}/min, {rpd}/day"
                           for m, (rpm, rpd) in ctx.settings.gemini_model_limits.items() if rpd)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model"))
        model_row.addWidget(self.model, 1)
        model_row.addWidget(QLabel(limits))
        where = ("Windows Credential Manager / OS keychain" if self.store.secure
                 else f"{self.store.path} (no OS credential store available)")
        info = QLabel(f"Keys are stored in: {where}. They never appear in logs or exports.\n"
                      "Keys from .env are shown too but can only be changed there.")
        info.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(acts)
        lay.addWidget(add_box)
        lay.addLayout(model_row)
        lay.addWidget(info)
        lay.addWidget(bb)
        self._reload()

    def _reload(self) -> None:
        env_keys = [k for k in self.ctx.settings.gemini_keys if not k.label.startswith("ui:")]
        rows = [(k.label, k.project, _mask(self.store.secret(k.label)),
                 "credential store" if k.in_keyring else "keys.json", True) for k in self.store.list()]
        rows += [(k.label, k.project, _mask(k.api_key), ".env", False) for k in env_keys]
        self.table.setRowCount(len(rows))
        for r, (name, proj, masked, where, editable) in enumerate(rows):
            for c, v in enumerate((name, proj, masked, where)):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, (name, editable))
                self.table.setItem(r, c, it)
        # Refresh the live settings so new keys are used immediately.
        self.ctx.settings.gemini_keys = env_keys + self.store.gemini_keys()

    def _selected(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 else None

    def _add(self) -> None:
        label = self.label.text().strip() or f"key{len(self.store.list()) + 1}"
        try:
            self.store.add(label, self.project.text(), self.secret.text())
        except ValueError as e:
            QMessageBox.warning(self, "Add key", str(e))
            return
        self.secret.clear()
        self.label.clear()
        self._reload()

    def _remove(self) -> None:
        sel = self._selected()
        if not sel:
            return
        name, editable = sel
        if not editable:
            QMessageBox.information(self, "Remove key", "This key comes from .env; remove it there.")
            return
        if QMessageBox.question(self, "Remove key", f"Remove key '{name}'?") == QMessageBox.Yes:
            self.store.remove(name)
            self._reload()

    def _test(self) -> None:
        sel = self._selected()
        if not sel:
            return
        name, editable = sel
        secret = self.store.secret(name) if editable else next(
            (k.api_key for k in self.ctx.settings.gemini_keys if k.label == name), "")
        model = self.model.currentText().strip() or self.ctx.settings.gemini_model
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            shown = test_key(secret, model)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            msg = str(e).replace(secret, "***")
            QMessageBox.warning(self, "Key test failed", f"'{name}' could not access {model}:\n\n{msg[:600]}")
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Key works", f"'{name}' can use {model} ({shown}).\n"
                                "This check uses no generation quota.")

    def done(self, r):
        s = self.ctx.settings
        model = self.model.currentText().strip()
        if model and model != s.gemini_model:
            s.gemini_model = model
            s.save_preferences()
        super().done(r)

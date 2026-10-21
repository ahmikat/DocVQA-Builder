"""Gemini API keys managed from the UI.

Secrets live in the OS credential store (Windows Credential Manager, macOS
Keychain, Secret Service) via `keyring`. Only labels and project names are
written to `~/.bndocvqa/keys.json`. If no credential store is available, keys
fall back to that JSON file, which is created readable only by the user where
the OS supports it. Keys from environment variables / .env still work and are
listed separately (read-only).
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .settings import GeminiKey

SERVICE = "bndocvqa-gemini"


def _config_dir() -> Path:
    return Path(os.environ.get("BNDOCVQA_CONFIG_DIR") or Path.home() / ".bndocvqa")


@dataclass
class StoredKey:
    label: str
    project: str
    in_keyring: bool = True


class KeyStore:
    def __init__(self, config_dir: Path | None = None, use_keyring: bool = True):
        self.dir = config_dir or _config_dir()
        self.path = self.dir / "keys.json"
        self._kr = None
        if use_keyring:
            try:
                import keyring
                from keyring.backends.fail import Keyring as FailKeyring
                if not isinstance(keyring.get_keyring(), FailKeyring):
                    self._kr = keyring
            except Exception:
                self._kr = None

    @property
    def secure(self) -> bool:
        return self._kr is not None

    # -- persistence --------------------------------------------------------
    def _read(self) -> dict:
        if not self.path.is_file():
            return {"keys": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    # -- API ------------------------------------------------------------------
    def list(self) -> list[StoredKey]:
        return [StoredKey(k["label"], k["project"], "secret" not in k) for k in self._read()["keys"]]

    def add(self, label: str, project: str, api_key: str) -> None:
        # Without a project name a key counts as its own project, so it has its own quota.
        label, api_key = label.strip(), api_key.strip()
        project = project.strip() or label
        if not label or not api_key:
            raise ValueError("label and API key are required")
        data = self._read()
        if any(k["label"] == label for k in data["keys"]):
            raise ValueError(f"a key named '{label}' already exists")
        entry = {"label": label, "project": project}
        if self._kr is not None:
            self._kr.set_password(SERVICE, label, api_key)
        else:
            entry["secret"] = api_key
        data["keys"].append(entry)
        self._write(data)

    def remove(self, label: str) -> None:
        data = self._read()
        data["keys"] = [k for k in data["keys"] if k["label"] != label]
        self._write(data)
        if self._kr is not None:
            try:
                self._kr.delete_password(SERVICE, label)
            except Exception:
                pass

    def set_project(self, label: str, project: str) -> None:
        data = self._read()
        for k in data["keys"]:
            if k["label"] == label:
                k["project"] = project.strip() or label
        self._write(data)

    def secret(self, label: str) -> str:
        for k in self._read()["keys"]:
            if k["label"] == label:
                if "secret" in k:
                    return k["secret"]
                return (self._kr.get_password(SERVICE, label) if self._kr else "") or ""
        return ""

    def gemini_keys(self) -> list[GeminiKey]:
        out = []
        for k in self.list():
            s = self.secret(k.label)
            if s:
                out.append(GeminiKey(f"ui:{k.label}", k.project, s))
        return out

"""Logging with secret redaction."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from ..config import Settings

_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")


class RedactingFilter(logging.Filter):
    """Removes configured API keys and anything shaped like a Google API key."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return _KEY_PATTERN.sub("***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        record.msg = self.redact(msg)
        record.args = ()
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def redact(text: str, secrets: list[str] | None = None) -> str:
    return RedactingFilter(secrets or []).redact(text)


_configured = False


def configure_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("bndocvqa")
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redactor = RedactingFilter(settings.secret_values())
    fh = RotatingFileHandler(settings.logs_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(redactor)
    root.addHandler(fh)
    _configured = True

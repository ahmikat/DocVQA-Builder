"""Application context: settings, database and repositories in one place."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Settings, load_settings
from ..database import Database, DocumentRepo, JobRepo, PageRepo, QuestionRepo, open_database
from .logging_setup import configure_logging


@dataclass
class AppContext:
    settings: Settings
    db: Database

    def __post_init__(self):
        self.documents = DocumentRepo(self.db)
        self.pages = PageRepo(self.db)
        self.questions = QuestionRepo(self.db)
        self.jobs = JobRepo(self.db)

    @property
    def data_dir(self) -> Path:
        return self.settings.data_dir

    def abs_path(self, rel: str) -> Path:
        from .files import resolve_inside
        return resolve_inside(self.settings.data_dir, rel)


def open_context(data_dir: str | Path | None = None, settings: Settings | None = None,
                 log: bool = True) -> AppContext:
    s = settings or load_settings(data_dir)
    s.ensure_dirs()
    if log:
        configure_logging(s)
    return AppContext(s, open_database(s.db_path))

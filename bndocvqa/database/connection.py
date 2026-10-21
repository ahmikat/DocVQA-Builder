"""SQLite connection management and migrations."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thread-aware SQLite access.

    Each thread gets its own connection. Use `tx()` for any multi-statement
    write so that it commits or rolls back as one unit.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        self._write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 30000")
        if self.path != ":memory:":
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
        return con

    @property
    def con(self) -> sqlite3.Connection:
        c = getattr(self._local, "con", None)
        if c is None:
            c = self._connect()
            self._local.con = c
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        con = self.con
        if con.in_transaction:  # nested: join the outer transaction
            yield con
            return
        with self._write_lock:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except BaseException:
                con.execute("ROLLBACK")
                raise
            else:
                con.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.con.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.con.execute(sql, params).fetchone()

    def close(self) -> None:
        c = getattr(self._local, "con", None)
        if c is not None:
            c.close()
            self._local.con = None

    # -- migrations ---------------------------------------------------------

    def schema_version(self) -> int:
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        row = self.query_one("SELECT MAX(version) AS v FROM schema_migrations")
        return int(row["v"] or 0)

    def migrate(self) -> list[int]:
        """Apply pending migrations in order; returns the versions applied."""
        current = self.schema_version()
        applied = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(f.name.split("_", 1)[0])
            if version <= current:
                continue
            sql = f.read_text(encoding="utf-8")
            with self.tx() as con:
                for stmt in _split_sql(sql):
                    con.execute(stmt)
                con.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                            (version, utcnow()))
            applied.append(version)
        return applied


def _split_sql(sql: str) -> list[str]:
    """Split a migration script into statements (no triggers/strings with ';')."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def open_database(path: str | Path) -> Database:
    db = Database(path)
    db.migrate()
    return db

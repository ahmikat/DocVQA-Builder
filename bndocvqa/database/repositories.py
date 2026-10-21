"""Repositories: the only code that writes SQL for domain records."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, fields
from typing import Iterable, Optional

from ..models.records import DONE, Document, Job, Option, Page, Question
from .connection import Database, utcnow


def _row_to(cls, row: sqlite3.Row, **overrides):
    names = {f.name for f in fields(cls)}
    data = {k: row[k] for k in row.keys() if k in names}
    data.update(overrides)
    return cls(**data)


class DocumentRepo:
    COLS = [f.name for f in fields(Document)]

    def __init__(self, db: Database):
        self.db = db

    def next_number(self, con: sqlite3.Connection) -> int:
        """Next N for doc_N. Never reuses a number, even after removal."""
        r = con.execute("SELECT value FROM meta WHERE key='next_document_number'").fetchone()
        n = int(r[0]) if r else 1
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('next_document_number', ?)", (str(n + 1),))
        return n

    def insert(self, doc: Document, con: sqlite3.Connection) -> None:
        con.execute(f"INSERT INTO documents ({','.join(self.COLS)}) VALUES ({','.join('?' * len(self.COLS))})",
                    [getattr(doc, c) for c in self.COLS])

    def get(self, document_id: str) -> Optional[Document]:
        r = self.db.query_one("SELECT * FROM documents WHERE document_id=?", (document_id,))
        return _row_to(Document, r) if r else None

    def by_hash(self, file_hash: str) -> Optional[Document]:
        r = self.db.query_one("SELECT * FROM documents WHERE file_hash=?", (file_hash,))
        return _row_to(Document, r) if r else None

    def list(self) -> list[Document]:
        return [_row_to(Document, r) for r in self.db.query("SELECT * FROM documents ORDER BY rowid")]

    def delete(self, document_id: str) -> None:
        with self.db.tx() as con:
            con.execute("DELETE FROM documents WHERE document_id=?", (document_id,))

    def page_status_counts(self) -> dict[str, Counter]:
        out: dict[str, Counter] = {}
        for r in self.db.query("SELECT document_id, status, COUNT(*) n FROM pages GROUP BY document_id, status"):
            out.setdefault(r["document_id"], Counter())[r["status"]] = r["n"]
        return out

    def is_finished(self, document_id: str) -> bool:
        r = self.db.query_one("SELECT COUNT(*) total, SUM(status='done') done FROM pages WHERE document_id=?",
                              (document_id,))
        return bool(r["total"]) and r["total"] == (r["done"] or 0)


class PageRepo:
    COLS = [f.name for f in fields(Page)]

    def __init__(self, db: Database):
        self.db = db

    def insert(self, page: Page, con: sqlite3.Connection) -> None:
        con.execute(f"INSERT INTO pages ({','.join(self.COLS)}) VALUES ({','.join('?' * len(self.COLS))})",
                    [getattr(page, c) for c in self.COLS])

    def get(self, page_id: str) -> Optional[Page]:
        r = self.db.query_one("SELECT * FROM pages WHERE page_id=?", (page_id,))
        return _row_to(Page, r) if r else None

    def for_document(self, document_id: str) -> list[Page]:
        return [_row_to(Page, r) for r in
                self.db.query("SELECT * FROM pages WHERE document_id=? ORDER BY page_number", (document_id,))]

    def set_content(self, page_id: str, content_type: str, content_note: str, con: sqlite3.Connection) -> None:
        con.execute("UPDATE pages SET content_type=?, content_note=? WHERE page_id=?",
                    (content_type, content_note, page_id))

    def set_status(self, page_id: str, status: str, error: str = "", con: sqlite3.Connection | None = None) -> None:
        sql = "UPDATE pages SET status=?, error=? WHERE page_id=?"
        if con is not None:
            con.execute(sql, (status, error, page_id))
            return
        with self.db.tx() as c:
            c.execute(sql, (status, error, page_id))


class QuestionRepo:
    SCALAR = [f.name for f in fields(Question) if f.name not in ("options", "sub_axes")]

    def __init__(self, db: Database):
        self.db = db

    def replace_for_page(self, page_id: str, questions: list[Question], con: sqlite3.Connection) -> None:
        """Make `questions` the page's full question set (idempotent for retries)."""
        con.execute("DELETE FROM questions WHERE page_id=?", (page_id,))
        for q in questions:
            self._insert(con, q)

    def _insert(self, con: sqlite3.Connection, q: Question) -> None:
        now = utcnow()
        q.created_at = q.created_at or now
        q.updated_at = q.updated_at or now
        vals = [int(getattr(q, k)) if k == "edited" else getattr(q, k) for k in self.SCALAR]
        con.execute(f"INSERT INTO questions ({','.join(self.SCALAR)}) VALUES ({','.join('?' * len(self.SCALAR))})",
                    vals)
        self._children(con, q)

    def _children(self, con: sqlite3.Connection, q: Question) -> None:
        con.execute("DELETE FROM question_options WHERE question_id=?", (q.question_id,))
        con.execute("DELETE FROM question_sub_axes WHERE question_id=?", (q.question_id,))
        con.executemany("INSERT INTO question_options VALUES (?,?,?)",
                        [(q.question_id, o.label, o.text) for o in q.options])
        con.executemany("INSERT INTO question_sub_axes VALUES (?,?)",
                        [(q.question_id, a) for a in dict.fromkeys(q.sub_axes)])

    def save_edit(self, q: Question) -> Question:
        """Save a manual edit; the previous version is kept in question_history."""
        with self.db.tx() as con:
            before = self.get(q.question_id)
            if before is None:
                raise KeyError(q.question_id)
            con.execute("INSERT INTO question_history (question_id, changed_at, snapshot) VALUES (?,?,?)",
                        (q.question_id, utcnow(), json.dumps(asdict(before), ensure_ascii=False)))
            q.updated_at = utcnow()
            q.edited = True
            sets = ",".join(f"{k}=?" for k in self.SCALAR if k != "question_id")
            con.execute(f"UPDATE questions SET {sets} WHERE question_id=?",
                        [int(getattr(q, k)) if k == "edited" else getattr(q, k)
                         for k in self.SCALAR if k != "question_id"] + [q.question_id])
            self._children(con, q)
        return q

    def get(self, question_id: str) -> Optional[Question]:
        qs = self._load("WHERE q.question_id=?", (question_id,))
        return qs[0] if qs else None

    def for_document(self, document_id: str) -> list[Question]:
        return self._load("WHERE q.document_id=? ORDER BY p.page_number, q.question_number", (document_id,))

    def for_documents(self, document_ids: Iterable[str]) -> list[Question]:
        ids = list(document_ids)
        if not ids:
            return []
        return self._load(f"WHERE q.document_id IN ({','.join('?' * len(ids))}) "
                          "ORDER BY q.document_id, p.page_number, q.question_number", tuple(ids))

    def counts_by_document(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.db.query("SELECT document_id, COUNT(*) FROM questions GROUP BY document_id")}

    def _load(self, where: str, params: tuple) -> list[Question]:
        rows = self.db.query(f"SELECT q.* FROM questions q JOIN pages p ON p.page_id=q.page_id {where}", params)
        out: dict[str, Question] = {}
        for r in rows:
            out[r["question_id"]] = _row_to(Question, r, edited=bool(r["edited"]))
        if not out:
            return []
        ids = list(out)
        marks = ",".join("?" * len(ids))
        for r in self.db.query(f"SELECT * FROM question_options WHERE question_id IN ({marks}) ORDER BY label", ids):
            out[r["question_id"]].options.append(Option(r["label"], r["text"]))
        for r in self.db.query(f"SELECT * FROM question_sub_axes WHERE question_id IN ({marks}) ORDER BY axis_code",
                               ids):
            out[r["question_id"]].sub_axes.append(r["axis_code"])
        return list(out.values())


class JobRepo:
    COLS = [f.name for f in fields(Job)]

    def __init__(self, db: Database):
        self.db = db

    def enqueue(self, job: Job) -> tuple[Job, bool]:
        """Insert unless a job with the same key exists; a failed/cancelled one is re-queued."""
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM jobs WHERE idempotency_key=?", (job.idempotency_key,)).fetchone()
            if r is not None:
                existing = _row_to(Job, r)
                if existing.status in ("failed", "cancelled", "succeeded"):
                    c.execute("UPDATE jobs SET status='queued', error='', attempts=0, next_attempt_at='' "
                              "WHERE job_id=?", (existing.job_id,))
                    existing.status = "queued"
                return existing, False
            job.created_at = job.created_at or utcnow()
            c.execute(f"INSERT INTO jobs ({','.join(self.COLS)}) VALUES ({','.join('?' * len(self.COLS))})",
                      [getattr(job, k) for k in self.COLS])
            return job, True

    def get(self, job_id: str) -> Optional[Job]:
        r = self.db.query_one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        return _row_to(Job, r) if r else None

    def list(self, statuses: Iterable[str] | None = None) -> list[Job]:
        sql, params = "SELECT * FROM jobs", []
        if statuses:
            st = list(statuses)
            sql += f" WHERE status IN ({','.join('?' * len(st))})"
            params = st
        return [_row_to(Job, r) for r in self.db.query(sql + " ORDER BY created_at, rowid", tuple(params))]

    def active_for_document(self, document_id: str) -> list[Job]:
        return [_row_to(Job, r) for r in self.db.query(
            "SELECT * FROM jobs WHERE document_id=? AND status IN ('queued','running')", (document_id,))]

    def claim_next(self, now: str) -> Optional[Job]:
        with self.db.tx() as c:
            r = c.execute("SELECT job_id FROM jobs WHERE status='queued' AND (next_attempt_at='' OR next_attempt_at<=?)"
                          " ORDER BY created_at, rowid LIMIT 1", (now,)).fetchone()
            if r is None:
                return None
            c.execute("UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE job_id=?",
                      (utcnow(), r[0]))
        return self.get(r[0])

    def update(self, job_id: str, **values) -> None:
        sets = ",".join(f"{k}=?" for k in values)
        with self.db.tx() as c:
            c.execute(f"UPDATE jobs SET {sets} WHERE job_id=?", [*values.values(), job_id])

    def status(self, job_id: str) -> str:
        r = self.db.query_one("SELECT status FROM jobs WHERE job_id=?", (job_id,))
        return r[0] if r else ""

    def recover_interrupted(self) -> int:
        with self.db.tx() as c:
            return c.execute("UPDATE jobs SET status='queued' WHERE status='running'").rowcount

    def cancel_for_document(self, document_id: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE jobs SET status='cancelled' WHERE document_id=? AND status IN ('queued','running')",
                      (document_id,))

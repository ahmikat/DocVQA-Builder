"""Persistent request log for daily quota accounting."""
from __future__ import annotations

from datetime import datetime, timezone

from ...database import Database
from .ratelimit import quota_day_start


class RequestLog:
    def __init__(self, db: Database):
        self.db = db

    def record(self, project: str, model: str, at: datetime) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO api_requests (project, model, at) VALUES (?,?,?)",
                      (project, model, at.astimezone(timezone.utc).isoformat(timespec="seconds")))

    def count_since(self, project: str, model: str, since: datetime) -> int:
        r = self.db.query_one("SELECT COUNT(*) FROM api_requests WHERE project=? AND model=? AND at>=?",
                              (project, model, since.astimezone(timezone.utc).isoformat(timespec="seconds")))
        return int(r[0])

    def today_by_model(self) -> dict[str, int]:
        """Requests per model in the current quota day, summed over projects."""
        since = quota_day_start().isoformat(timespec="seconds")
        return {r[0]: r[1] for r in self.db.query(
            "SELECT model, COUNT(*) FROM api_requests WHERE at>=? GROUP BY model ORDER BY model", (since,))}


def quota_summary(settings, db: Database) -> str:
    """'model used/limit, ...' for the current Pacific-time quota day."""
    used = RequestLog(db).today_by_model()
    models = dict.fromkeys([settings.gemini_model, *used])
    parts = []
    for m in models:
        rpd = settings.gemini_model_limits.get(m, (0, 0))[1] or settings.gemini_default_rpd
        parts.append(f"{m} {used.get(m, 0)}/{rpd or '∞'}")
    return "Requests today (resets midnight Pacific): " + ", ".join(parts)

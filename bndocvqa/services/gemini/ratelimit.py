"""Per-project, per-model rate limiting (requests per minute and per day).

Gemini quota belongs to a Google Cloud project and applies per model. All
keys of one project share one limiter, so configuring more keys for the same
project never raises throughput. Extra keys in a project are only used for
failover when a key is rejected (e.g. revoked).

Daily quotas reset at midnight Pacific time. Daily counts are persisted
(see RequestLog) so restarting the app does not reset them.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ...config import GeminiKey

QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def quota_day_start(now: datetime | None = None) -> datetime:
    """Start (UTC) of the current Gemini quota day."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(QUOTA_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_quota_reset(now: datetime | None = None) -> datetime:
    """Next midnight Pacific time, in UTC."""
    return _next_local_midnight(now or datetime.now(timezone.utc))


def _next_local_midnight(now: datetime) -> datetime:
    local = now.astimezone(QUOTA_TZ)
    nxt = (local + timedelta(days=1)).date()
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=QUOTA_TZ).astimezone(timezone.utc)


class QuotaExhausted(Exception):
    """The daily quota for a model is used up; retry after `reset_at` (UTC)."""

    def __init__(self, model: str, reset_at: datetime):
        super().__init__(f"daily quota for {model} reached; resumes after "
                         f"{reset_at.astimezone(QUOTA_TZ):%Y-%m-%d %H:%M %Z}")
        self.model = model
        self.reset_at = reset_at


class MemoryRequestLog:
    """In-memory request log (tests, or when no database is available)."""

    def __init__(self):
        self._rows: list[tuple[str, str, datetime]] = []
        self._lock = threading.Lock()

    def record(self, project: str, model: str, at: datetime) -> None:
        with self._lock:
            self._rows.append((project, model, at))

    def count_since(self, project: str, model: str, since: datetime) -> int:
        with self._lock:
            return sum(1 for p, m, t in self._rows if p == project and m == model and t >= since)


class RequestLimiter:
    """Sliding-window limiter: at most `rpm` request starts per 60 s."""

    def __init__(self, rpm: int, clock=time.monotonic):
        self.rpm = max(1, int(rpm))
        self._clock = clock
        self._starts: list[float] = []
        self._lock = threading.Lock()
        self._cooldown_until = 0.0

    def wait_time(self) -> float:
        with self._lock:
            now = self._clock()
            self._starts = [t for t in self._starts if now - t < 60.0]
            wait = max(0.0, self._cooldown_until - now)
            if len(self._starts) >= self.rpm:
                wait = max(wait, 60.0 - (now - self._starts[0]))
            return wait

    def try_acquire(self) -> bool:
        with self._lock:
            now = self._clock()
            self._starts = [t for t in self._starts if now - t < 60.0]
            if now < self._cooldown_until or len(self._starts) >= self.rpm:
                return False
            self._starts.append(now)
            return True

    def cooldown(self, seconds: float) -> None:
        """Pause after a 429 from the server."""
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, self._clock() + seconds)


@dataclass
class ProjectPool:
    project: str
    keys: list[GeminiKey] = field(default_factory=list)
    disabled: set[str] = field(default_factory=set)  # labels of rejected keys
    _next: int = 0

    def active_key(self) -> GeminiKey | None:
        live = [k for k in self.keys if k.label not in self.disabled]
        if not live:
            return None
        return live[self._next % len(live)]


class KeyPool:
    """Chooses a project with free capacity for a model, and an active key for it."""

    def __init__(self, keys: list[GeminiKey], default_rpm: int, project_rpm: dict[str, int] | None = None,
                 model_limits: dict[str, tuple[int, int]] | None = None, default_rpd: int = 0,
                 request_log=None, clock=time.monotonic, sleep=time.sleep, now=None):
        self.default_rpm = default_rpm
        self.project_rpm = project_rpm or {}
        self.model_limits = model_limits or {}  # model -> (rpm, rpd); 0 = use defaults / unlimited
        self.default_rpd = default_rpd
        self.log = request_log or MemoryRequestLog()
        self.projects: dict[str, ProjectPool] = {}
        for k in keys:
            self.projects.setdefault(k.project, ProjectPool(k.project)).keys.append(k)
        self._limiters: dict[tuple[str, str], RequestLimiter] = {}
        self._exhausted_until: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))

    def __bool__(self) -> bool:
        return any(p.active_key() for p in self.projects.values())

    def rpm_for(self, project: str, model: str) -> int:
        rpm = self.model_limits.get(model, (0, 0))[0]
        return rpm or self.project_rpm.get(project, self.default_rpm)

    def rpd_for(self, model: str) -> int:
        rpd = self.model_limits.get(model, (0, 0))[1]
        return rpd or self.default_rpd

    def limiter(self, project: str, model: str) -> RequestLimiter:
        key = (project, model)
        if key not in self._limiters:
            self._limiters[key] = RequestLimiter(self.rpm_for(project, model), self._clock)
        return self._limiters[key]

    def used_today(self, project: str, model: str) -> int:
        return self.log.count_since(project, model, quota_day_start(self._now()))

    def _daily_blocked(self, project: str, model: str) -> bool:
        now = self._now()
        until = self._exhausted_until.get((project, model))
        if until and now < until:
            return True
        rpd = self.rpd_for(model)
        return bool(rpd) and self.used_today(project, model) >= rpd

    def mark_exhausted(self, project: str, model: str) -> datetime:
        """Server says the daily quota is gone (even if our count disagrees)."""
        reset = _next_local_midnight(self._now())
        with self._lock:
            self._exhausted_until[(project, model)] = reset
        return reset

    def acquire(self, model: str, cancelled=lambda: False, max_wait: float = 600.0) -> tuple[ProjectPool, GeminiKey]:
        waited = 0.0
        while True:
            with self._lock:
                best_wait = None
                usable = 0
                for pool in self.projects.values():
                    key = pool.active_key()
                    if key is None:
                        continue
                    usable += 1
                    if self._daily_blocked(pool.project, model):
                        continue
                    lim = self.limiter(pool.project, model)
                    if lim.try_acquire():
                        self.log.record(pool.project, model, self._now())
                        return pool, key
                    w = lim.wait_time()
                    best_wait = w if best_wait is None else min(best_wait, w)
            if usable == 0:
                raise RuntimeError("no usable Gemini API keys configured")
            if best_wait is None:  # every project is out of daily quota for this model
                raise QuotaExhausted(model, _next_local_midnight(self._now()))
            if cancelled():
                raise InterruptedError("cancelled while waiting for rate limit")
            step = min(max(best_wait, 0.05), 1.0)
            self._sleep(step)
            waited += step
            if waited > max_wait:
                raise TimeoutError("timed out waiting for rate-limit capacity")

    def has_capacity_elsewhere(self, project: str, model: str) -> bool:
        """Another project with a live key, not out of daily quota and not cooling down."""
        for p in self.projects.values():
            if p.project == project or p.active_key() is None or self._daily_blocked(p.project, model):
                continue
            if self.limiter(p.project, model)._cooldown_until <= self._clock():
                return True
        return False

    def disable_key(self, pool: ProjectPool, key: GeminiKey) -> None:
        with self._lock:
            pool.disabled.add(key.label)
            pool._next += 1

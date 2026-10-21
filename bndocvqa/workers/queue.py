"""Persistent, resumable job queue with bounded concurrency.

Jobs live in the database, so a crash or restart loses nothing: jobs that
were `running` are re-queued on start and, being idempotent, safely re-run.
Transient failures are retried with exponential backoff by scheduling
`next_attempt_at`, not by blocking a worker.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from ..database import utcnow
from ..models.records import Job
from ..services.context import AppContext
from ..services.gemini.parsing import ResponseParseError
from ..services.gemini.provider import PermanentError, Provider, TransientError, backoff_delay
from ..services.gemini.ratelimit import QuotaExhausted
from ..services.logging_setup import redact
from ..services.pipeline import Pipeline

log = logging.getLogger(__name__)

# (event, job) where event in started/succeeded/failed/retry/deferred/cancelled
EventCallback = Callable[[str, Job], None]


class JobRunner:
    def __init__(self, ctx: AppContext, provider_factory: Callable[[], Provider], concurrency: int | None = None,
                 on_event: Optional[EventCallback] = None, sleep=time.sleep, rng=None):
        self.ctx = ctx
        self.pipeline = Pipeline(ctx)
        self._provider_factory = provider_factory
        self._provider: Optional[Provider] = None
        self._provider_lock = threading.Lock()
        self.concurrency = max(1, concurrency or ctx.settings.gemini_concurrency)
        self.on_event = on_event
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._sleep = sleep
        self._rng = rng

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        n = self.ctx.jobs.recover_interrupted()
        if n:
            log.info("re-queued %d interrupted job(s)", n)
        self._stop.clear()
        for i in range(self.concurrency):
            t = threading.Thread(target=self._loop, name=f"job-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.ctx.jobs.claim_next(utcnow())
            if job is None:
                self._stop.wait(1.0)
                continue
            self.process(job)
        self.ctx.db.close()

    def run_until_idle(self, max_jobs: int = 10_000, wait_for_backoff: bool = True,
                       max_backoff_wait: float = 600.0) -> int:
        """Process jobs on the calling thread until none remain (CLI and tests).

        Stops instead of waiting when the next runnable job is further away
        than `max_backoff_wait` seconds (e.g. parked until the daily quota resets).
        """
        self.ctx.jobs.recover_interrupted()
        n = 0
        while n < max_jobs:
            job = self.ctx.jobs.claim_next(utcnow())
            if job is None:
                pending = self.ctx.jobs.list(statuses=("queued",))
                if not pending or not wait_for_backoff:
                    break
                soonest = min(j.next_attempt_at for j in pending if j.next_attempt_at) if any(
                    j.next_attempt_at for j in pending) else ""
                delay = _seconds_until(soonest) if soonest else 0.0
                if delay > max_backoff_wait:
                    log.info("remaining jobs are parked until %s; stopping", soonest)
                    break
                self._sleep(max(0.0, min(delay, 300.0)))
                continue
            self.process(job)
            n += 1
        return n

    # -- one job ----------------------------------------------------------
    def provider(self) -> Provider:
        with self._provider_lock:
            if self._provider is None:
                self._provider = self._provider_factory()
            return self._provider

    def _emit(self, event: str, job_id: str) -> None:
        if self.on_event:
            try:
                self.on_event(event, self.ctx.jobs.get(job_id))
            except Exception:
                log.exception("event callback failed")

    def process(self, job: Job) -> None:
        jid = job.job_id
        self._emit("started", jid)

        def cancelled() -> bool:
            return self._stop.is_set() or self.ctx.jobs.status(jid) == "cancelled"

        try:
            if cancelled():
                raise InterruptedError("cancelled")
            outcome = self.pipeline.run(job, self.provider(), cancelled)
        except InterruptedError:
            if self.ctx.jobs.status(jid) != "cancelled":  # stopped by shutdown: re-queue
                self.ctx.jobs.update(jid, status="queued")
            self._emit("cancelled", jid)
            return
        except QuotaExhausted as e:
            self._defer(job, e)
            return
        except (TransientError, ResponseParseError, TimeoutError) as e:
            self._fail_or_retry(job, e, retryable=True)
            return
        except (PermanentError, PermissionError, KeyError, ValueError) as e:
            self._fail_or_retry(job, e, retryable=False)
            return
        except Exception as e:  # unexpected: record, don't crash the worker
            log.exception("job %s crashed", jid)
            self._fail_or_retry(job, e, retryable=False)
            return

        if self.ctx.jobs.status(jid) == "cancelled":
            self._emit("cancelled", jid)
            return
        cur = self.ctx.jobs.get(jid)
        self.ctx.jobs.update(
            jid, status="succeeded", finished_at=utcnow(), error="", result_summary=outcome.summary,
            prompt_tokens=cur.prompt_tokens + outcome.usage.prompt_tokens,
            output_tokens=cur.output_tokens + outcome.usage.output_tokens,
            thoughts_tokens=cur.thoughts_tokens + outcome.usage.thoughts_tokens,
            raw_response=outcome.raw[:200_000])
        log.info("job %s (%s) succeeded: %s", jid, job.page_id, outcome.summary)
        self._emit("succeeded", jid)

    def _defer(self, job: Job, e: QuotaExhausted) -> None:
        """Daily quota is used up: park the job until the reset without spending an attempt."""
        cur = self.ctx.jobs.get(job.job_id)
        if cur.status == "cancelled":
            self._emit("cancelled", job.job_id)
            return
        self.ctx.jobs.update(job.job_id, status="queued", attempts=max(0, cur.attempts - 1), error=str(e),
                             next_attempt_at=e.reset_at.isoformat(timespec="seconds"))
        log.warning("job %s deferred: %s", job.job_id, e)
        self._emit("deferred", job.job_id)

    def _fail_or_retry(self, job: Job, e: Exception, retryable: bool) -> None:
        msg = redact(f"{type(e).__name__}: {e}", self.ctx.settings.secret_values())[:2000]
        cur = self.ctx.jobs.get(job.job_id)
        if cur.status == "cancelled":
            self._emit("cancelled", job.job_id)
            return
        if isinstance(e, TransientError) and e.rate_limited:
            # A per-minute 429 says nothing about the page itself: wait as asked and try again
            # without using up one of the page's attempts.
            delay = e.retry_after or 30.0
            when = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
            self.ctx.jobs.update(job.job_id, status="queued", attempts=max(0, cur.attempts - 1),
                                 error=f"rate limited; retrying in {delay:.0f}s", next_attempt_at=when)
            log.info("job %s rate limited; retry in %.0fs", job.job_id, delay)
            self._emit("retry", job.job_id)
        elif retryable and cur.attempts < cur.max_attempts:
            delay = backoff_delay(cur.attempts, **({"rng": self._rng} if self._rng else {}))
            if isinstance(e, TransientError) and e.retry_after:
                delay = max(delay, e.retry_after)
            when = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
            self.ctx.jobs.update(job.job_id, status="queued", error=f"attempt {cur.attempts}: {msg}",
                                 next_attempt_at=when)
            log.warning("job %s retry in %.0fs: %s", job.job_id, delay, msg)
            self._emit("retry", job.job_id)
        else:
            self.ctx.jobs.update(job.job_id, status="failed", error=msg, finished_at=utcnow())
            self.pipeline.mark_failed(job, msg)
            log.error("job %s failed: %s", job.job_id, msg)
            self._emit("failed", job.job_id)


def _seconds_until(iso: str) -> float:
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return 0.0
    return (t - datetime.now(timezone.utc)).total_seconds()

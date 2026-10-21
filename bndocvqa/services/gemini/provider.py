"""Gemini provider built on Google's official `google-genai` SDK.

The provider interface (`generate_json`) is small so tests can substitute a
fake without network access or API keys.
"""
from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ...config import Settings
from ..logging_setup import redact
from .parsing import ResponseParseError, extract_json
from .ratelimit import KeyPool, QuotaExhausted

log = logging.getLogger(__name__)


@dataclass
class ImagePart:
    data: bytes
    mime_type: str
    label: str = ""  # text placed before the image, e.g. "পৃষ্ঠা ২ (page_id=...)"


@dataclass
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.thoughts_tokens += other.thoughts_tokens


@dataclass
class GenerationResult:
    data: Any
    raw_text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""


class TransientError(Exception):
    """Retry with backoff (429, 5xx, timeouts, connection errors)."""

    def __init__(self, msg: str, rate_limited: bool = False, retry_after: float | None = None):
        super().__init__(msg)
        self.rate_limited = rate_limited
        self.retry_after = retry_after


class PermanentError(Exception):
    """Do not retry (bad request, unsupported model, safety block)."""


class ResponseBlocked(PermanentError):
    """Gemini refused to answer for this input (safety/policy block)."""


class KeyRejected(Exception):
    """The API key itself was refused (401/403)."""


class Provider(Protocol):
    def generate_json(self, model: str, prompt: str, images: list[ImagePart], schema: dict | None,
                      temperature: float, cancelled: Callable[[], bool] = lambda: False) -> GenerationResult: ...


def parse_retry_delay(message: str) -> float | None:
    """Seconds Google asks us to wait, from '"retryDelay": "23s"' or 'Please retry in 23.4s'."""
    m = (re.search(r"retry[_ ]?delay[\"']?\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)s", message, re.IGNORECASE)
         or re.search(r"retry in (\d+(?:\.\d+)?)\s*s", message, re.IGNORECASE))
    return min(float(m.group(1)) + 1.0, 120.0) if m else None


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 120.0, rng=random.random) -> float:
    """Exponential backoff with full jitter: attempt 1 -> up to 2 s, 2 -> 4 s, ..."""
    return rng() * min(cap, base * (2 ** (attempt - 1))) + 0.5


class GeminiProvider:
    """Real provider. Handles key selection, rate limits and in-call retries."""

    def __init__(self, settings: Settings, sleep=time.sleep, request_log=None):
        if not settings.gemini_keys:
            raise RuntimeError("no Gemini API key configured (add one with the 'Gemini API keys' button)")
        self.settings = settings
        self.pool = KeyPool(settings.gemini_keys, settings.gemini_default_rpm, settings.gemini_project_rpm,
                            model_limits=settings.gemini_model_limits, default_rpd=settings.gemini_default_rpd,
                            request_log=request_log)
        self._clients: dict[str, Any] = {}
        self._sleep = sleep
        self._secrets = settings.secret_values()

    def _client(self, key):
        if key.label not in self._clients:
            from google import genai
            from google.genai import types
            self._clients[key.label] = genai.Client(
                api_key=key.api_key,
                http_options=types.HttpOptions(timeout=int(self.settings.gemini_timeout_s * 1000)))
        return self._clients[key.label]

    def generate_json(self, model, prompt, images, schema, temperature, cancelled=lambda: False):
        from google.genai import types
        parts: list[Any] = []
        for im in images:
            if im.label:
                parts.append(types.Part.from_text(text=im.label))
            parts.append(types.Part.from_bytes(data=im.data, mime_type=im.mime_type))
        parts.append(types.Part.from_text(text=prompt))
        cfg = dict(temperature=temperature, response_mime_type="application/json")
        if schema:
            cfg["response_json_schema"] = schema
        config = types.GenerateContentConfig(**cfg)

        resp = self._send(model, parts, config, cancelled)

        return self._parse(resp, model)

    def _send(self, model, parts, config, cancelled):
        """Send one request, moving on to the next project's key when one runs out.

        A rejected key, a project whose daily quota is used up, or a project that is
        rate-limited right now does not fail the request while another project can
        take it. QuotaExhausted is raised only when every project is out for today.
        """
        from google.genai import types
        last: Exception | None = None
        for _ in range(2 * sum(len(p.keys) for p in self.pool.projects.values()) + 1):
            pool, key = self.pool.acquire(model, cancelled)  # skips exhausted projects
            try:
                return self._client(key).models.generate_content(
                    model=model, contents=[types.Content(role="user", parts=parts)], config=config)
            except Exception as e:  # classify SDK/transport errors
                err = self._classify(e)
            if isinstance(err, KeyRejected):
                self.pool.disable_key(pool, key)
                log.warning("key %s (project %s) rejected; disabled for this session", key.label, pool.project)
                if not self.pool:
                    raise PermanentError("all configured API keys were rejected")
                last = err
                continue
            if isinstance(err, QuotaExhausted):
                self.pool.mark_exhausted(pool.project, model)
                log.warning("project %s: daily quota for %s used up; trying the next project", pool.project, model)
                last = err
                continue
            if isinstance(err, TransientError) and err.rate_limited:
                self.pool.limiter(pool.project, model).cooldown(err.retry_after or 30.0)
                if self.pool.has_capacity_elsewhere(pool.project, model):
                    last = err
                    continue
            raise err
        raise last if isinstance(last, TransientError) else TransientError(f"no project could take the request: {last}")

    def _parse(self, resp, model) -> GenerationResult:
        usage = Usage()
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            usage = Usage(um.prompt_token_count or 0, um.candidates_token_count or 0,
                          getattr(um, "thoughts_token_count", 0) or 0)
        text = getattr(resp, "text", None)
        if not text:
            reason = ""
            try:
                reason = str(resp.candidates[0].finish_reason)
            except Exception:
                pass
            if "SAFETY" in reason or "PROHIBITED" in reason:
                raise ResponseBlocked(f"response blocked: {reason}")
            raise ResponseParseError(f"empty response (finish_reason={reason})")
        return GenerationResult(extract_json(text), text, usage, model)

    def _classify(self, e: Exception) -> Exception:
        msg = redact(f"{type(e).__name__}: {e}", self._secrets)[:800]
        code = getattr(e, "code", None)
        try:
            import httpx
            if isinstance(e, (httpx.TimeoutException, httpx.TransportError)):
                return TransientError(msg)
        except ImportError:
            pass
        if isinstance(e, (TimeoutError, ConnectionError)):
            return TransientError(msg)
        if code == 429:
            if re.search(r"per[ _-]?day|PerDay|daily", msg, re.IGNORECASE):
                return QuotaExhausted("", datetime.now(timezone.utc))  # reset time filled in by caller
            return TransientError(msg, rate_limited=True, retry_after=parse_retry_delay(msg))
        # Google reports bad keys as 400 INVALID_ARGUMENT ("API key not valid"), and
        # expired, suspended or leaked keys as 400/403; all mean "use another key".
        if re.search(r"API[_ ]key[_ ](not[_ ]valid|invalid|expired)|API_KEY_INVALID|key (has been|was) "
                     r"(suspended|revoked|reported as leaked)|PERMISSION_DENIED", msg, re.IGNORECASE)                 or code == 401:
            return KeyRejected(msg)
        if isinstance(code, int) and (code >= 500 or code == 408):
            return TransientError(msg)
        if isinstance(code, int) and 400 <= code < 500:
            return PermanentError(msg)
        return TransientError(msg)

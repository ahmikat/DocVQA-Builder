from datetime import datetime, timezone

import pytest

from bndocvqa.config import GeminiKey, load_settings
from bndocvqa.config.keystore import KeyStore
from bndocvqa.config.settings import parse_model_limits
from bndocvqa.services.gemini import GeminiProvider
from bndocvqa.services.gemini.provider import TransientError
from bndocvqa.services.gemini.ratelimit import KeyPool, QuotaExhausted, next_quota_reset
from bndocvqa.services.gemini.usage import RequestLog, quota_summary
from bndocvqa.services.logging_setup import RedactingFilter


def test_limiter_is_per_project_not_per_key():
    t = [0.0]
    keys = [GeminiKey("a", "p1", "k1"), GeminiKey("b", "p1", "k2")]
    pool = KeyPool(keys, default_rpm=2, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    pool.acquire("m")
    pool.acquire("m")
    before = t[0]
    pool.acquire("m")
    assert t[0] - before >= 59


def test_daily_quota_per_model():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    pool = KeyPool([GeminiKey("a", "p1", "k1")], 100, model_limits={"lite": (0, 2)}, now=lambda: now,
                   sleep=lambda s: None)
    pool.acquire("lite")
    pool.acquire("lite")
    with pytest.raises(QuotaExhausted) as e:
        pool.acquire("lite")
    assert e.value.reset_at == next_quota_reset(now) == datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)
    pool.acquire("other")


def test_daily_counts_persist(ctx):
    keys = [GeminiKey("a", "p1", "k1")]
    for _ in range(2):
        KeyPool(keys, 100, model_limits={"lite": (0, 2)}, request_log=RequestLog(ctx.db)).acquire("lite")
    with pytest.raises(QuotaExhausted):
        KeyPool(keys, 100, model_limits={"lite": (0, 2)}, request_log=RequestLog(ctx.db)).acquire("lite")
    ctx.settings.gemini_model = "lite"
    ctx.settings.gemini_model_limits = {"lite": (0, 2)}
    assert "lite 2/2" in quota_summary(ctx.settings, ctx.db)


def test_per_day_429_is_quota(ctx):
    prov = GeminiProvider(ctx.settings)
    e = type("E", (Exception,), {"code": 429})("GenerateRequestsPerDayPerProjectPerModel exceeded")
    assert isinstance(prov._classify(e), QuotaExhausted)
    e2 = type("E", (Exception,), {"code": 429})("GenerateRequestsPerMinutePerProjectPerModel")
    assert isinstance(prov._classify(e2), TransientError)


def test_settings_defaults_and_env(tmp_path):
    s = load_settings(tmp_path, env={"GEMINI_API_KEY_1": "AIzaS1", "GEMINI_PROJECT_1": "p1",
                                     "GEMINI_MODEL_LIMITS": "x=10/30"}, dotenv_path=None)
    assert s.gemini_model == "gemini-3.5-flash-lite" and s.gemini_model_limits["gemini-3.5-flash-lite"] == (15, 500)
    assert s.gemini_model_limits["x"] == (10, 30) and [k.project for k in s.gemini_keys] == ["p1"]
    assert parse_model_limits("a=/5") == {"a": (0, 5)}


def test_keystore_roundtrip(tmp_path):
    ks = KeyStore(tmp_path, use_keyring=False)
    ks.add("k1", "proj-a", "AIzaSECRET")
    ks.add("k2", "", "AIzaOTHER")
    assert [(k.label, k.project) for k in ks.list()] == [("k1", "proj-a"), ("k2", "k2")]
    assert [k.label for k in ks.gemini_keys()] == ["ui:k1", "ui:k2"]
    with pytest.raises(ValueError):
        ks.add("k1", "x", "y")
    ks.remove("k1")
    assert [k.label for k in ks.list()] == ["k2"]


def test_log_redaction():
    import logging
    f = RedactingFilter(["my-secret"])
    rec = logging.LogRecord("x", logging.ERROR, "f", 1, "key=%s AIzaAAAAAAAAAAAAAAAAAAAAAAAA", ("my-secret",), None)
    f.filter(rec)
    assert "my-secret" not in rec.getMessage() and "AIza" not in rec.getMessage()


def test_default_limits_are_15_per_minute(tmp_path):
    s = load_settings(tmp_path, env={}, dotenv_path=None)
    pool = KeyPool([GeminiKey("a", "p1", "k")], s.gemini_default_rpm, model_limits=s.gemini_model_limits)
    assert pool.rpm_for("p1", "gemini-3.5-flash-lite") == 15 and pool.rpd_for("gemini-3.5-flash-lite") == 500
    assert pool.rpm_for("p1", "gemini-3.8-flash") == 15 and pool.rpd_for("gemini-3.8-flash") == 20
    assert s.gemini_concurrency == 3


def test_never_more_than_15_starts_per_minute():
    t = [0.0]
    pool = KeyPool([GeminiKey("a", "p1", "k")], 15, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    starts = []
    for _ in range(45):
        pool.acquire("m")
        starts.append(t[0])
    for i in range(len(starts)):
        assert sum(1 for x in starts if starts[i] <= x < starts[i] + 60) <= 15


def test_parse_retry_delay():
    from bndocvqa.services.gemini.provider import parse_retry_delay
    assert parse_retry_delay('{"@type": "RetryInfo", "retryDelay": "23s"}') == 24.0
    assert parse_retry_delay("Please retry in 7.5s.") == 8.5
    assert parse_retry_delay("quota exceeded") is None


def test_rate_limited_retries_do_not_use_attempts(ctx, doc):
    from bndocvqa.services.pipeline import Pipeline
    from conftest import ITEMS, FakeProvider, run
    ctx.settings.gemini_max_attempts = 2
    many_429 = [TransientError("429", rate_limited=True, retry_after=0.01) for _ in range(5)]
    Pipeline(ctx).process_document("doc_1")
    run(ctx, FakeProvider(many_429 + [{"page_type": "text", "questions": ITEMS}, {"page_type": "text", "questions": []}]))
    assert ctx.documents.is_finished("doc_1")


# --- failover between projects (fake SDK clients, no network) --------------------
from types import SimpleNamespace as NS  # noqa: E402

from bndocvqa.config import Settings  # noqa: E402


class _ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _ok_client(calls, label):
    def generate_content(**kw):
        calls.append(label)
        return NS(text='{"page_type": "text", "questions": []}', candidates=[],
                  usage_metadata=NS(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0))
    return NS(models=NS(generate_content=generate_content))


def _failing_client(calls, label, code, msg):
    def generate_content(**kw):
        calls.append(label)
        raise _ApiError(code, msg)
    return NS(models=NS(generate_content=generate_content))


def _provider(*keys):
    s = Settings(gemini_keys=list(keys), gemini_model_limits={})
    return GeminiProvider(s, sleep=lambda x: None)


def test_daily_quota_on_one_project_moves_to_next_key():
    prov = _provider(GeminiKey("k1", "p1", "AIza1"), GeminiKey("k2", "p2", "AIza2"))
    calls = []
    prov._clients = {"k1": _failing_client(calls, "k1", 429, "GenerateRequestsPerDayPerProjectPerModel exceeded"),
                     "k2": _ok_client(calls, "k2")}
    res = prov.generate_json("m", "p", [], None, 0.1)
    assert res.data["page_type"] == "text" and calls == ["k1", "k2"]
    calls.clear()
    prov.generate_json("m", "p", [], None, 0.1)
    assert calls == ["k2"]  # p1 stays marked exhausted for today


def test_all_projects_out_of_daily_quota_raises_quota_exhausted():
    prov = _provider(GeminiKey("k1", "p1", "AIza1"), GeminiKey("k2", "p2", "AIza2"))
    calls = []
    msg = "GenerateRequestsPerDayPerProjectPerModel exceeded"
    prov._clients = {"k1": _failing_client(calls, "k1", 429, msg), "k2": _failing_client(calls, "k2", 429, msg)}
    with pytest.raises(QuotaExhausted):
        prov.generate_json("m", "p", [], None, 0.1)


def test_per_minute_429_uses_another_project_right_away():
    prov = _provider(GeminiKey("k1", "p1", "AIza1"), GeminiKey("k2", "p2", "AIza2"))
    calls = []
    prov._clients = {"k1": _failing_client(calls, "k1", 429, "PerMinute exceeded; Please retry in 20s"),
                     "k2": _ok_client(calls, "k2")}
    prov.generate_json("m", "p", [], None, 0.1)
    assert calls == ["k1", "k2"]


def test_rejected_key_falls_back_to_next_key():
    prov = _provider(GeminiKey("k1", "p1", "AIza1"), GeminiKey("k2", "p1", "AIza2"))
    calls = []
    prov._clients = {"k1": _failing_client(calls, "k1", 400, "API key not valid. Please pass a valid API key."),
                     "k2": _ok_client(calls, "k2")}
    prov.generate_json("m", "p", [], None, 0.1)
    assert calls == ["k1", "k2"]


@pytest.mark.parametrize("code,msg", [
    (400, "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key."),
    (400, "API_KEY_INVALID"),
    (400, "API key expired. Please renew the API key."),
    (403, "403 PERMISSION_DENIED. Your API key was reported as leaked."),
])
def test_bad_key_errors_are_key_rejections(ctx, code, msg):
    from bndocvqa.services.gemini.provider import KeyRejected
    assert isinstance(GeminiProvider(ctx.settings)._classify(_ApiError(code, msg)), KeyRejected)


def test_ordinary_bad_request_is_not_a_key_problem(ctx):
    from bndocvqa.services.gemini.provider import PermanentError
    assert isinstance(GeminiProvider(ctx.settings)._classify(_ApiError(400, "Request payload size exceeds")),
                      PermanentError)


def test_keys_without_project_get_their_own_quota(tmp_path):
    s = load_settings(tmp_path, env={"GEMINI_API_KEY_1": "AIza1", "GEMINI_API_KEY_2": "AIza2"}, dotenv_path=None)
    assert [k.project for k in s.gemini_keys] == ["key1", "key2"]

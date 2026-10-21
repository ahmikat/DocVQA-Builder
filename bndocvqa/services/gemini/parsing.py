"""Robust parsing of model JSON output."""
from __future__ import annotations

import json
import re
from typing import Any


class ResponseParseError(ValueError):
    """The model output was not valid JSON of the expected shape."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse JSON, tolerating code fences and leading/trailing prose."""
    if text is None or not str(text).strip():
        raise ResponseParseError("empty response")
    t = str(text).strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} or [...] block.
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise ResponseParseError("no JSON object found in response")
    start = min(starts)
    end = max(t.rfind("}"), t.rfind("]"))
    if end <= start:
        raise ResponseParseError("unterminated JSON in response")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise ResponseParseError(f"malformed JSON: {e.msg} at {e.pos}") from e


def require_list(obj: Any, key: str) -> list:
    if not isinstance(obj, dict) or not isinstance(obj.get(key), list):
        raise ResponseParseError(f"expected an object with a '{key}' list")
    return obj[key]


def as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;]", v) if x.strip()]
    if isinstance(v, list):
        return [as_str(x).strip() for x in v if as_str(x).strip()]
    return []


def as_int(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        m = re.search(r"\d+", as_str(v).translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")))
        return int(m.group()) if m else None

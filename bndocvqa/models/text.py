"""Bangla-aware text normalization helpers."""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_TO_ASCII_DIGITS = str.maketrans({b: str(i) for i, b in enumerate(BN_DIGITS)})


def normalize_answer(text: str | None) -> str:
    """Matching normalization for answer_bn vs. option text.

    Unicode NFC and whitespace collapsing only. Bengali and Arabic digits are
    deliberately NOT folded (researcher decision): numeral script must match.
    """
    if text is None:
        return ""
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fold_for_equivalence(text: str | None) -> str:
    """Aggressive folding used only to detect *equivalent* options.

    Two options that differ only in digit script, punctuation, case or
    thousands separators (e.g. "৮০০ টাকা" vs "800 টাকা") are equivalent and
    must not both appear in one MCQ.
    """
    t = normalize_answer(text).translate(_TO_ASCII_DIGITS).casefold()
    t = re.sub(r"(?<=\d)[,،](?=\d)", "", t)
    t = re.sub(r"[।\.\,;:!?\"'“”‘’()\[\]{}\-–—/]", " ", t)
    return _WS.sub(" ", t).strip()


_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def numeric_values(text: str | None) -> list[float]:
    """Extract numbers (Bengali or Arabic digits, with thousands separators)."""
    t = normalize_answer(text).translate(_TO_ASCII_DIGITS)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    return [float(x) for x in _NUM.findall(t)]


def char_ngrams(text: str, n: int = 3) -> set[str]:
    t = fold_for_equivalence(text).replace(" ", "")
    if len(t) < n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def is_bangla(ch: str) -> bool:
    return "ঀ" <= ch <= "৿"


def script_profile(text: str) -> str:
    """Rough language profile from character counts: bn, en, mixed or unknown."""
    bn = sum(1 for c in text if is_bangla(c) and not ("০" <= c <= "৯"))
    en = sum(1 for c in text if "a" <= c.lower() <= "z")
    total = bn + en
    if total < 20:
        return "unknown"
    if bn / total >= 0.9:
        return "bn"
    if en / total >= 0.9:
        return "en"
    return "mixed"

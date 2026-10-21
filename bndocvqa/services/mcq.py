"""Turn one item of Gemini's page response into a well-formed MCQ, or drop it.

This is response parsing, not review: an item that cannot form a proper
question (no text, unknown axis, fewer than four distinct distractors, no
valid claim outcome) is dropped instead of being stored half-built.
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Optional

from ..models.records import Option, Question
from ..models.taxonomy import (ABSTAIN_TEXT, AXIS_BY_CODE, CLAIM_CONTRADICTED, CLAIM_INSUFFICIENT, CLAIM_SUPPORTED,
                               FORMAT_MCQ5, FORMAT_VERIFY3, MCQ5_LABELS, TYPE_ABSTENTION, VERIFY3_OPTIONS,
                               expected_format, expected_type)
from ..models.text import fold_for_equivalence, normalize_answer
from .gemini.parsing import as_str, as_str_list

BANNED_OPTION_RE = re.compile(
    r"all of the above|none of the above|উপরের\s*সব|উপরোক্ত\s*সব|সবগুলো(ই)?\s*(সঠিক)?$|কোনো?টিই\s*নয়|উপরের\s*কোনো?টিই",
    re.IGNORECASE)
ABSTAIN_LIKE_RE = re.compile(r"উল্লেখ\s*(নেই|করা\s*হয়নি)|তথ্য\s*নেই|not\s+(mentioned|stated|given)", re.IGNORECASE)


def normalize_claim_outcome(answer: str) -> str:
    """Map a free-text claim verdict to a canonical outcome, or '' if unclear.

    Contradiction cues are tested before support cues: 'অসত্য' contains 'সত্য'.
    """
    a = normalize_answer(answer)
    if "অপর্যাপ্ত" in a or "insufficient" in a.lower():
        return CLAIM_INSUFFICIENT
    if any(k in a for k in ("খণ্ডনকৃত", "খন্ডনকৃত", "মিথ্যা", "অসত্য")) or "contradict" in a.lower():
        return CLAIM_CONTRADICTED
    if any(k in a for k in ("সমর্থিত", "সত্য", "হ্যাঁ")) or "support" in a.lower():
        return CLAIM_SUPPORTED
    return ""


def _fraction(key: str) -> float:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16) / float(16 ** 12)


def clean_distractors(correct: str, raw: list[str]) -> list[str]:
    """Distinct, non-equivalent distractors; banned and 'not mentioned' phrasings removed."""
    seen = {fold_for_equivalence(correct)}
    out = []
    for t in raw:
        t = normalize_answer(t)
        f = fold_for_equivalence(t)
        if not t or f in seen or BANNED_OPTION_RE.search(t) or ABSTAIN_LIKE_RE.search(t) or t == ABSTAIN_TEXT:
            continue
        seen.add(f)
        out.append(t)
    return out


def build_question(item: dict, question_id: str, abstain_ratio: float) -> Optional[Question]:
    """Build a Question (ids filled in by the caller) or None if the item is unusable."""
    if not isinstance(item, dict):
        return None
    text = normalize_answer(as_str(item.get("question_bn")))
    axis = as_str(item.get("primary_axis")).strip().upper()[:3]
    if not text or axis not in AXIS_BY_CODE:
        return None
    sub = []
    for a in as_str_list(item.get("sub_axes")):
        a = a.strip().upper()[:3]
        if a in AXIS_BY_CODE and a != axis and a not in ("B03", "B04") and a not in sub:
            sub.append(a)

    q = Question(question_id=question_id, document_id="", page_id="", question_number=0, question_bn=text,
                 question_format=expected_format(axis), question_type=expected_type(axis), primary_axis=axis,
                 sub_axes=sub, evidence_snippet=normalize_answer(as_str(item.get("evidence_snippet"))),
                 rationale=normalize_answer(as_str(item.get("rationale"))))

    if q.question_format == FORMAT_VERIFY3:
        outcome = normalize_claim_outcome(as_str(item.get("claim_outcome")) or as_str(item.get("correct_answer")))
        if not outcome:
            return None
        q.options = [Option(lb, t) for lb, t in VERIFY3_OPTIONS.items()]
        q.correct_option = next(lb for lb, t in VERIFY3_OPTIONS.items() if t == outcome)
        q.answer_bn = outcome
        return q

    correct = ABSTAIN_TEXT if q.question_type == TYPE_ABSTENTION else normalize_answer(as_str(item.get("correct_answer")))
    if not correct or (q.question_type != TYPE_ABSTENTION and ABSTAIN_LIKE_RE.search(correct)):
        return None
    distractors = clean_distractors(correct, as_str_list(item.get("distractors")))
    if len(distractors) < 4:
        return None
    distractors = distractors[:4]
    # Use the abstention text as a distractor in a share of ordinary questions, so that its
    # presence among the options never gives away a B03 answer.
    if q.question_type != TYPE_ABSTENTION and _fraction("abstain:" + question_id) < abstain_ratio:
        distractors[-1] = ABSTAIN_TEXT
    # Shuffle so the correct position carries no signal (deterministic per question id).
    rng = random.Random(question_id)
    texts = [correct] + distractors
    rng.shuffle(texts)
    q.options = [Option(lb, t) for lb, t in zip(MCQ5_LABELS, texts)]
    q.correct_option = MCQ5_LABELS[texts.index(correct)]
    q.answer_bn = correct
    assert q.question_format == FORMAT_MCQ5
    return q

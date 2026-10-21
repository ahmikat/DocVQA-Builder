from collections import Counter

import pytest

from bndocvqa.models.taxonomy import ABSTAIN_TEXT
from bndocvqa.services.mcq import build_question, normalize_claim_outcome
from conftest import ITEMS


def build(item, qid="doc_1_p1_q1", ratio=0.0):
    return build_question(item, qid, ratio)


def test_answerable_has_five_unique_options_and_one_answer():
    q = build(ITEMS[0])
    texts = [o.text for o in q.options]
    assert [o.label for o in q.options] == list("ABCDE") and len(set(texts)) == 5
    assert q.answer_bn == q.option_text(q.correct_option) == "জেলা শিক্ষা অফিস"
    assert q.sub_axes == ["C01"] and q.question_type == "answerable"


def test_correct_position_is_shuffled_and_deterministic():
    positions = Counter(build(ITEMS[0], f"doc_1_p1_q{i}").correct_option for i in range(200))
    assert len(positions) == 5 and min(positions.values()) > 20
    assert build(ITEMS[0], "x").correct_option == build(ITEMS[0], "x").correct_option


def test_abstention_answer_is_canonical():
    q = build(ITEMS[1])
    assert q.question_type == "abstention" and q.answer_bn == ABSTAIN_TEXT
    assert len(q.options) == 5


def test_claim_uses_three_fixed_options():
    q = build(ITEMS[2])
    assert q.question_format == "verify3" and [o.text for o in q.options] == ["সমর্থিত", "খণ্ডনকৃত", "অপর্যাপ্ত তথ্য"]
    assert q.correct_option == "B" and q.answer_bn == "খণ্ডনকৃত"


@pytest.mark.parametrize("raw,expected", [
    ("সমর্থিত (দাবিটি সঠিক)", "সমর্থিত"), ("দাবিটি অসত্য", "খণ্ডনকৃত"), ("মিথ্যা", "খণ্ডনকৃত"),
    ("অপর্যাপ্ত তথ্য", "অপর্যাপ্ত তথ্য"), ("জানি না", ""),
])
def test_claim_outcome_normalization(raw, expected):
    assert normalize_claim_outcome(raw) == expected


def test_malformed_items_are_dropped():
    assert build({**ITEMS[0], "primary_axis": "C99"}) is None
    assert build({**ITEMS[0], "question_bn": ""}) is None
    assert build({**ITEMS[0], "distractors": ["ক", "খ", "ক"]}) is None
    assert build({**ITEMS[2], "claim_outcome": "?", "correct_answer": "?"}) is None
    assert build("not a dict") is None


def test_equivalent_and_banned_distractors_removed():
    item = {**ITEMS[0], "correct_answer": "৮০০ টাকা",
            "distractors": ["800 টাকা", "উপরের সবগুলো", "নথিতে উল্লেখ নেই", "৭০০ টাকা", "৯০০ টাকা", "১০০ টাকা", "৬০০ টাকা"]}
    q = build(item)
    assert sorted(o.text for o in q.options) == sorted(["৮০০ টাকা", "৭০০ টাকা", "৯০০ টাকা", "১০০ টাকা", "৬০০ টাকা"])


def test_abstain_text_used_as_distractor_by_ratio():
    qs = [build(ITEMS[0], f"doc_1_p1_q{i}", ratio=0.3) for i in range(300)]
    share = sum(ABSTAIN_TEXT in [o.text for o in q.options] for q in qs) / len(qs)
    assert 0.2 < share < 0.4
    assert all(q.answer_bn != ABSTAIN_TEXT for q in qs)

"""Benchmark evaluation of model predictions.

Inputs
  references: JSONL records with answers (private/questions.jsonl, a dev file,
              or test.jsonl joined with private/test_answers.jsonl)
  predictions: JSONL lines {"question_id": ..., "prediction": "C"}; the
              prediction may also be the option text, which is mapped back
              to its label.

Five-option MCQ (mcq5) and three-option claim verification (verify3) are
scored and reported separately, since their chance levels differ (20% vs 33%).
Missing predictions count as wrong and are reported.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..models.taxonomy import ABSTAIN_TEXT, VERIFY3_OPTIONS
from ..models.text import normalize_answer


def load_jsonl(path: str | Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{ln}: invalid JSON ({e.msg})") from e
    return out


def load_references(path: str | Path, answers_path: str | Path | None = None) -> dict[str, dict]:
    refs = {r["question_id"]: r for r in load_jsonl(path)}
    if answers_path:
        for a in load_jsonl(answers_path):
            if a["question_id"] in refs:
                refs[a["question_id"]].update(a)
    missing = [q for q, r in refs.items() if not r.get("correct_option")]
    if missing:
        raise ValueError(f"{len(missing)} reference record(s) lack correct_option (pass the answer key)")
    return refs


def _to_label(pred, ref: dict) -> str:
    if pred is None:
        return ""
    p = normalize_answer(str(pred))
    labels = set(ref["options"])
    if p.upper() in labels:
        return p.upper()
    m = re.fullmatch(r"\(?([A-Ea-e])[\).:]?(\s.*)?", p)
    if m and m.group(1).upper() in labels:
        return m.group(1).upper()
    for lb, t in ref["options"].items():
        if normalize_answer(t) == p:
            return lb
    return "?"  # unparseable prediction


def _acc(rows: list[dict]) -> dict:
    n = len(rows)
    c = sum(r["correct"] for r in rows)
    return {"n": n, "correct": c, "accuracy": round(c / n, 4) if n else None}


def evaluate(refs: dict[str, dict], predictions: list[dict]) -> dict:
    preds = {}
    for p in predictions:
        qid = p.get("question_id")
        if qid in preds:
            raise ValueError(f"duplicate prediction for {qid}")
        preds[qid] = p.get("prediction", p.get("predicted_option"))
    unknown = sorted(set(preds) - set(refs))
    rows = []
    for qid, r in refs.items():
        raw = preds.get(qid)
        label = _to_label(raw, r) if qid in preds else ""
        doc = r.get("document") or {}
        rows.append({
            "question_id": qid, "question_format": r["question_format"], "question_type": r.get("question_type"),
            "primary_axis": r.get("primary_axis"), "document_type": doc.get("document_type", ""),
            "language_profile": doc.get("language_profile", ""), "difficulty": r.get("difficulty") or "",
            "reference": r["correct_option"], "prediction": label, "raw_prediction": raw,
            "missing": qid not in preds, "unparseable": label == "?",
            "correct": label == r["correct_option"],
            "predicted_abstain": label in r["options"] and normalize_answer(r["options"][label]) == ABSTAIN_TEXT,
            "has_abstain_option": any(normalize_answer(t) == ABSTAIN_TEXT for t in r["options"].values()),
        })

    def group(fmt_rows, key):
        g = defaultdict(list)
        for x in fmt_rows:
            g[x[key] or "(unset)"].append(x)
        return {k: _acc(v) for k, v in sorted(g.items())}

    result = {"n_references": len(refs), "n_predictions": len(preds),
              "missing_predictions": sum(r["missing"] for r in rows),
              "unparseable_predictions": sum(r["unparseable"] for r in rows),
              "unknown_question_ids": unknown, "formats": {}}
    for fmt in ("mcq5", "verify3"):
        fr = [x for x in rows if x["question_format"] == fmt]
        if not fr:
            continue
        block = {"overall": _acc(fr), "by_primary_axis": group(fr, "primary_axis"),
                 "by_document_type": group(fr, "document_type"), "by_language_profile": group(fr, "language_profile"),
                 "by_question_type": group(fr, "question_type")}
        if any(x["difficulty"] for x in fr):
            block["by_difficulty"] = group(fr, "difficulty")
        if fmt == "verify3":
            names = VERIFY3_OPTIONS
            cm = Counter((names.get(x["reference"], x["reference"]), names.get(x["prediction"], x["prediction"] or "-"))
                         for x in fr)
            block["confusion"] = [{"reference": a, "prediction": b, "count": n} for (a, b), n in sorted(cm.items())]
        else:
            abst = [x for x in fr if x["question_type"] == "abstention"]
            ans_with = [x for x in fr if x["question_type"] == "answerable" and x["has_abstain_option"]]
            block["abstention"] = {
                "abstention_questions": _acc(abst),
                "false_abstention_rate": round(sum(x["predicted_abstain"] for x in ans_with) / len(ans_with), 4)
                if ans_with else None,
                "answerable_with_abstain_option": len(ans_with),
            }
            block["position_confusion"] = dict(sorted(Counter(f"{x['reference']}->{x['prediction'] or '-'}"
                                                              for x in fr).items()))
        result["formats"][fmt] = block
    result["per_question"] = rows
    return result


def write_per_question_csv(result: dict, path: str | Path) -> None:
    rows = result["per_question"]
    cols = ["question_id", "question_format", "question_type", "primary_axis", "document_type",
            "language_profile", "difficulty", "reference", "prediction", "raw_prediction", "correct",
            "missing", "unparseable", "predicted_abstain"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def build_eval_prompts(public_records: list[dict]) -> list[dict]:
    """Model-facing prompts from PUBLIC records only (no answers present)."""
    out = []
    for r in public_records:
        if "correct_option" in r or "answer_bn" in r:
            raise ValueError("build_eval_prompts must be given public records without answers")
        opts = "\n".join(f"{lb}. {t}" for lb, t in sorted(r["options"].items()))
        letters = "/".join(sorted(r["options"]))
        out.append({
            "question_id": r["question_id"],
            "image_paths": [p for p in (r.get("image_paths") or {}).values() if p],
            "prompt": (f"প্রদত্ত নথির ছবি দেখে প্রশ্নের উত্তর দিন।\n\nপ্রশ্ন: {r['question_bn']}\n\n{opts}\n\n"
                       f"শুধু সঠিক বিকল্পের অক্ষরটি ({letters}) লিখুন।"),
        })
    return out

"""Shared fixtures: isolated workspace, synthetic documents, fake Gemini."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bndocvqa.config import GeminiKey, Settings  # noqa: E402
from bndocvqa.services.context import open_context  # noqa: E402
from bndocvqa.services.gemini.provider import GenerationResult, Usage  # noqa: E402
from bndocvqa.services.library import LibraryService  # noqa: E402
from bndocvqa.workers.queue import JobRunner  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "ws", render_dpi=50,
                    gemini_keys=[GeminiKey("k1", "proj", "AIzaFAKEKEY000000000000000000000")])


@pytest.fixture
def ctx(settings):
    c = open_context(settings=settings, log=False)
    yield c
    c.db.close()


def make_pdf(path: Path, pages: int = 2, marker: str = "") -> Path:
    """A small synthetic PDF; `marker` makes the file content (hash) distinct."""
    doc = pymupdf.open()
    for i in range(pages):
        pg = doc.new_page(width=300, height=400)
        pg.insert_text((30, 50), f"Synthetic notice {marker} page {i + 1}", fontsize=11)
        pg.draw_rect(pymupdf.Rect(30, 100 + 30 * i, 200, 300), fill=(0.2, 0.1 * i, 0))
    doc.save(path)
    doc.close()
    return path


def make_image(path: Path, color=(200, 200, 200)) -> Path:
    im = Image.new("RGB", (240, 320), color)
    ImageDraw.Draw(im).rectangle((20, 20, 120, 200), fill=(10, 10, 10))
    im.save(path)
    return path


@pytest.fixture
def doc(ctx, tmp_path):
    d, existing = LibraryService(ctx).import_file(make_pdf(tmp_path / "নোটিশ sample.pdf", 2, "A"))
    assert existing is None
    return d


ITEMS = [
    {"question_bn": "নোটিশটি কে জারি করেছে?", "primary_axis": "B01", "sub_axes": ["B01", "C01"],
     "correct_answer": "জেলা শিক্ষা অফিস",
     "distractors": ["উপজেলা শিক্ষা অফিস", "জেলা প্রশাসকের কার্যালয়", "শিক্ষা মন্ত্রণালয়", "মাধ্যমিক শিক্ষা বোর্ড"],
     "evidence_snippet": "জারিকারী: জেলা শিক্ষা অফিস", "rationale": "সরাসরি পাঠ"},
    {"question_bn": "সভার বাজেট কত?", "primary_axis": "B03", "correct_answer": "উল্লেখ নেই",
     "distractors": ["৫০,০০০ টাকা", "১ লাখ টাকা", "২০,০০০ টাকা", "শূন্য"], "evidence_snippet": "শুধু তারিখ ও স্থান আছে"},
    {"question_bn": "দাবিটি যাচাই করুন: 'সভা রবিবার হবে'", "primary_axis": "B04", "correct_answer": "খণ্ডনকৃত",
     "claim_outcome": "খণ্ডনকৃত (সোমবার)", "distractors": [], "evidence_snippet": "সভা সোমবার"},
]


class FakeProvider:
    """Returns scripted responses in order: a dict, an Exception to raise, or a callable(prompt)."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate_json(self, model, prompt, images, schema, temperature, cancelled=lambda: False):
        self.calls.append({"model": model, "images": len(images), "prompt": prompt})
        if not self.responses:
            raise AssertionError("no scripted response left")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(prompt)
        return GenerationResult(item, "{}", Usage(100, 50, 0), model)


def run(ctx, provider):
    runner = JobRunner(ctx, lambda: provider, sleep=lambda s: None, rng=lambda: 0.0)
    runner.run_until_idle()
    return runner

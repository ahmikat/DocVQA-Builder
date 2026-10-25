"""Hard maximum for Gemini-generated questions per document."""
from __future__ import annotations


def max_questions_for_document(page_count: int) -> int:
    if page_count < 1:
        return 0
    return {1: 5, 2: 8, 3: 10, 4: 12, 5: 15}.get(page_count, 20)

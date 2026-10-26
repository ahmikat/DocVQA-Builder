-- Preserve every page used by a manually imported question.
ALTER TABLE questions ADD COLUMN import_key TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX idx_questions_import_key ON questions(import_key) WHERE import_key <> '';

CREATE TABLE question_source_pages (
    question_id TEXT NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
    page_id TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 1),
    evidence_snippet TEXT NOT NULL DEFAULT '',
    used_for TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (question_id, page_id),
    UNIQUE (question_id, position)
);

CREATE TABLE question_reasoning_steps (
    question_id TEXT NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL CHECK (step_number >= 1),
    text TEXT NOT NULL,
    PRIMARY KEY (question_id, step_number)
);

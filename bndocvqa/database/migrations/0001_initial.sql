-- Schema. Paths are stored relative to the data directory.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE documents (
    document_id       TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    file_hash         TEXT NOT NULL UNIQUE,
    page_count        INTEGER NOT NULL DEFAULT 0,
    imported_at       TEXT NOT NULL
);

CREATE TABLE pages (
    page_id     TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    image_path  TEXT NOT NULL UNIQUE,
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','failed')),
    error       TEXT NOT NULL DEFAULT '',
    UNIQUE (document_id, page_number)
);

CREATE TABLE questions (
    question_id      TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_id          TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    question_number  INTEGER NOT NULL,
    question_bn      TEXT NOT NULL,
    question_format  TEXT NOT NULL CHECK (question_format IN ('mcq5','verify3')),
    question_type    TEXT NOT NULL CHECK (question_type IN ('answerable','abstention','claim_verification')),
    correct_option   TEXT NOT NULL,
    answer_bn        TEXT NOT NULL,
    primary_axis     TEXT NOT NULL,
    evidence_snippet TEXT NOT NULL DEFAULT '',
    rationale        TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL DEFAULT '',
    prompt_version   TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    edited           INTEGER NOT NULL DEFAULT 0,
    UNIQUE (page_id, question_number)
);
CREATE INDEX idx_questions_doc ON questions(document_id);

CREATE TABLE question_options (
    question_id TEXT NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
    label       TEXT NOT NULL CHECK (label IN ('A','B','C','D','E')),
    text        TEXT NOT NULL,
    PRIMARY KEY (question_id, label)
);

CREATE TABLE question_sub_axes (
    question_id TEXT NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
    axis_code   TEXT NOT NULL,
    PRIMARY KEY (question_id, axis_code)
);

-- Append-only record of manual edits (snapshot of the question before each save).
CREATE TABLE question_history (
    history_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    changed_at  TEXT NOT NULL,
    snapshot    TEXT NOT NULL
);

-- One job per page request.
CREATE TABLE jobs (
    job_id          TEXT PRIMARY KEY,
    page_id         TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    document_id     TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 4,
    error           TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    prompt_version  TEXT NOT NULL DEFAULT '',
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    thoughts_tokens INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT '',
    finished_at     TEXT NOT NULL DEFAULT '',
    next_attempt_at TEXT NOT NULL DEFAULT '',
    result_summary  TEXT NOT NULL DEFAULT '',
    raw_response    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_jobs_status ON jobs(status);

-- One row per Gemini request start, for per-model daily quota accounting.
CREATE TABLE api_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project    TEXT NOT NULL,
    model      TEXT NOT NULL,
    at         TEXT NOT NULL
);
CREATE INDEX idx_api_requests ON api_requests(project, model, at);

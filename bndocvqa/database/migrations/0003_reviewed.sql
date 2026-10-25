-- A manual Save is the release gate for question dataset files.
ALTER TABLE questions ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE questions ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT '';
-- Older versions marked every saved question as edited, even when unchanged.
UPDATE questions SET reviewed=1, reviewed_at=updated_at WHERE edited=1;
CREATE INDEX idx_questions_doc_reviewed ON questions(document_id, reviewed);

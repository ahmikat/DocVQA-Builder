-- What Gemini judged the page to contain, and why it has no questions (if so).
ALTER TABLE pages ADD COLUMN content_type TEXT NOT NULL DEFAULT '';
ALTER TABLE pages ADD COLUMN content_note TEXT NOT NULL DEFAULT '';

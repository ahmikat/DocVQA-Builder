# Portable workspace archive

Clicking **Export ZIP…** in the Library packages all current documents, pages and recovery data, including unfinished or failed pages. The main question dataset files and `index.html` contain **only questions manually saved in the View tab**. The HTML viewer also shows document/page metadata. Unsaved Gemini drafts remain in `data/` for recovery, but are not displayed in the HTML viewer. The chosen folder receives both a ZIP and an unpacked folder. The ZIP is checked for CRC errors before it is reported as complete.

```
bndocvqa_archive_<YYYYMMDD_HHMMSS>.zip
bndocvqa_archive_<YYYYMMDD_HHMMSS>/
  index.html        offline viewer with search, status and axis filters
  questions.json    saved question records as a JSON array
  questions.jsonl   one JSON object per question, UTF-8
  questions.csv     one row per question, UTF-8 with BOM (opens in Excel)
  questions.xlsx    spreadsheet
  data/state.json   full relational snapshot, including unsaved drafts, for rebuilding SQLite
  data/*.json       each application table as JSON
  data/*.csv        each application table as CSV, including empty tables
  manifest.json     table counts and SHA-256 of every payload file
  documents/        the original files, byte-for-byte: doc_1.pdf, doc_2.jpg, ...
  images/           page images: doc_1_p1.png, doc_1_p2.png, ...
```

`workspace/` has the same readable files and viewer while the app runs. SQLite remains the working database for transactions and resumable jobs. The JSON/CSV files are generated mirrors; edit through the app. To restore an archive into a fresh workspace, copy the unpacked contents to that workspace and start with `--data-dir` pointing to it. When no SQLite file exists, `data/state.json` rebuilds the working database. API keys and `.env` are never included.

## Question record (JSONL)

```json
{
  "question_id": "doc_1_p1_q2",
  "document_id": "doc_1",
  "document_path": "documents/doc_1.pdf",
  "page_id": "doc_1_p1",
  "page_number": 1,
  "image_path": "images/doc_1_p1.png",
  "question_bn": "…",
  "question_format": "mcq5",
  "question_type": "answerable",
  "options": {"A": "…", "B": "…", "C": "…", "D": "…", "E": "…"},
  "correct_option": "D",
  "answer_bn": "…",
  "primary_axis": "C02",
  "axis_name": "Table interpretation",
  "sub_axes": ["B01"],
  "evidence_snippet": "…",
  "rationale": "…",
  "edited": false,
  "reviewed": true,
  "reviewed_at": "2026-10-25T12:00:00+00:00",
  "model": "gemini-3.5-flash-lite",
  "prompt_version": "page-v4-reasoning",
  "source_file": "original-name.pdf"
}
```

The values above illustrate the schema. They are not an actual record.

- `question_format` is `mcq5` (options A–E) or `verify3` (B04: options A=`সমর্থিত`, B=`খণ্ডনকৃত`, C=`অপর্যাপ্ত তথ্য`).
- `question_type` is `answerable`, `abstention` (B03, answer `প্রদত্ত নথিতে উল্লেখ নেই`) or `claim_verification` (B04).
- `answer_bn` is always the text of `options[correct_option]`.
- `reviewed` is `true` after a manual Save in the View tab; only these records appear in the main dataset files. `reviewed_at` records the last Save time.
- `edited` is `true` when the question's content was changed in the View tab. Saving an unchanged question marks it reviewed without marking it edited.
- `document_path` and `image_path` are relative to the archive folder.
- `documents/` holds exact copies of the imported files. Their SHA-256 values can be checked against `data/documents.json` and `manifest.json`; `source_file` gives each one's original filename.

In the CSV, the options are in the columns `option_A` to `option_E`, and `sub_axes` is separated by `;`.

## Predictions (for `python -m bndocvqa evaluate`)

```json
{"question_id": "doc_1_p1_q2", "prediction": "D"}
```

`prediction` may be a label or the exact option text. `mcq5` and `verify3` accuracy are reported separately.

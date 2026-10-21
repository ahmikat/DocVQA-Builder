# Export format (v1.0)

Clicking **Export…** in the Library writes only **finished** documents, meaning every page has been processed. If you tick documents first, only the ticked finished ones are exported; with none ticked, every finished document is.

```
bndocvqa_export_<YYYYMMDD_HHMMSS>/
  index.html        open in a browser: pages with their questions, filter by axis
  questions.jsonl   one JSON object per question, UTF-8
  questions.csv     one row per question, UTF-8 with BOM (opens in Excel)
  questions.xlsx    spreadsheet
  manifest.json     versions, export time, documents, counts, SHA-256 of every file
  documents/        the original files, byte-for-byte: doc_1.pdf, doc_2.jpg, ...
  images/           page images: doc_1_p1.png, doc_1_p2.png, ...
```

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
  "model": "gemini-3.5-flash-lite",
  "prompt_version": "page-v1",
  "source_file": "original-name.pdf"
}
```

The values above illustrate the schema. They are not an actual record.

- `question_format` is `mcq5` (options A–E) or `verify3` (B04: options A=`সমর্থিত`, B=`খণ্ডনকৃত`, C=`অপর্যাপ্ত তথ্য`).
- `question_type` is `answerable`, `abstention` (B03, answer `প্রদত্ত নথিতে উল্লেখ নেই`) or `claim_verification` (B04).
- `answer_bn` is always the text of `options[correct_option]`.
- `edited` is `true` when the question was changed in the View tab.
- `document_path` and `image_path` are relative to the export folder.
- `documents/` holds exact copies of the imported files. Their SHA-256 values match `file_hash` in `manifest.json`, and `source_file` gives each one's original filename.

In the CSV, the options are in the columns `option_A` to `option_E`, and `sub_axes` is separated by `;`.

## Predictions (for `python -m bndocvqa evaluate`)

```json
{"question_id": "doc_1_p1_q2", "prediction": "D"}
```

`prediction` may be a label or the exact option text. `mcq5` and `verify3` accuracy are reported separately.

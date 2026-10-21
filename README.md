# Bangla DocVQA Benchmark Builder

A desktop app that turns Bangla and Bangla-English PDFs into a multiple-choice Document VQA dataset using Gemini.

## Install

Requires Python 3.11+.

```bash
pip install -r requirements.txt
```

## Use

```bash
python -m bndocvqa
```

1. **Gemini API keys…**: add one or more keys, each tagged with its Google Cloud project, and pick the model. Use **Test selected** to check a key; the test uses no quota.
2. **Import files…** or **Import folder…**: files are named `doc_1`, `doc_2`, … in import order.
3. Tick the documents you want, then click **▶ Process**.
   - Each page is sent to Gemini on its own (one request per page).
   - Gemini returns about 5 questions per page, fewer for sparse pages and more for dense ones. Each question comes with its answer, its primary and sub-axes from Taxonomy v4, and its options.
   - The **Status** column shows progress. If the daily quota runs out, pages wait and continue automatically after the reset (midnight Pacific time).
4. **View**: browse a document's pages and questions, filter by axis (with counts), and edit a question, then **Save**. Edited questions are marked, and the previous version is kept.
5. **Export…**: choose a folder. Only finished documents (every page processed) are exported, into `bndocvqa_export_<timestamp>/`. The export contains the original documents, the page images, the questions (JSONL, CSV, XLSX) and a manifest. Open its `index.html` in a browser to browse the result.

If a page fails, its row says so. Click **▶ Process** again to retry only the unfinished pages.

**Pages without questions.** Gemini first classifies every page (text, table, form, chart, cover, …). Some pages get no questions:
- blank pages;
- pages with only a QR code or barcode;
- pages with only signatures or stamps;
- pages with only a photo or logo;
- unreadable pages;
- pages Gemini refuses for safety reasons.

The app enforces this itself, not just through the prompt. These pages still count as processed, so the document can finish and be exported. The View tab and the export's `index.html` show the reason, e.g. "No questions on this page: signature or stamp, round seal and signature".

## What a question looks like

- 5 options (A–E) with exactly one correct, for every type except **B04** (claim verification). B04 has 3 fixed options: `সমর্থিত` / `খণ্ডনকৃত` / `অপর্যাপ্ত তথ্য`.
- **B03** (abstention) asks for something that is not on the page. Its answer is always `প্রদত্ত নথিতে উল্লেখ নেই`. That phrase also appears as a wrong option in about 30% of ordinary questions, so its presence doesn't give the answer away.
- The position of the correct option is shuffled.
- Items Gemini returns malformed are dropped instead of stored half-built: an unknown axis, fewer than four distinct wrong options, or an unclear claim verdict.

See [docs/EXPORT_SCHEMA.md](docs/EXPORT_SCHEMA.md) for the export format, [docs/GEMINI.md](docs/GEMINI.md) for keys and quotas, and [docs/TAXONOMY_v4.md](docs/TAXONOMY_v4.md) for the axes.

## Command line (optional)

```bash
python -m bndocvqa import path\to\pdfs
python -m bndocvqa list
python -m bndocvqa process doc_1 doc_2
python -m bndocvqa export D:\exports
python -m bndocvqa evaluate D:\exports\bndocvqa_export_...\questions.jsonl predictions.jsonl
```

## Where things are stored

- `workspace/` holds the database, the original files (read-only copies) and the page images. Removed documents go to `workspace/trash/`. It is git-ignored.
- API keys added in the app are kept in Windows Credential Manager, never in files, logs or exports. Keys can also come from a `.env` file instead (see `.env.example`); `.env` is git-ignored.

## Project layout

```
bndocvqa/
  config/      settings and the API key store
  models/      records, Taxonomy v4, Bangla text normalization
  database/    SQLite schema, migrations, repositories
  services/    import, Gemini client and rate limits, page processing, MCQ building, export, evaluation
  workers/     background job queue
  prompts/     the page prompt and its response schema
  ui/          PySide6 screens (Library, View)
tests/         pytest suite with synthetic PDFs and a mocked Gemini
docs/          taxonomy, export format, Gemini setup
pilot_data/    16 sample Bangladeshi documents to try the app with, plus an earlier pilot's output
```

## Tests

```bash
python -m pytest
```

The tests use a mocked Gemini, so they need no network access and no API key.

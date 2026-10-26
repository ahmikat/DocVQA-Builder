# Bangla DocVQA Benchmark Builder

A desktop app that turns Bangla and Bangla-English PDFs into a multiple-choice Document VQA dataset using Gemini.

## Install

Requires Python 3.11+ and an internet connection for the first dependency install.

```bash
git clone https://github.com/ahmikat/DocVQA-Builder.git
cd DocVQA-Builder
```

On Windows, double-click `Run Bangla DocVQA Builder.bat`. It creates a local
`.venv`, installs the dependencies, and starts the desktop app. On macOS or
Linux, create an environment and run the app from the repository folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bndocvqa
```

## Use

```bash
python -m bndocvqa
```

On Windows, you can also run `python -m bndocvqa` from an activated environment
if you want to see startup errors in a terminal.

1. **Gemini API keys…**: add one or more keys, each tagged with its Google Cloud project, and pick the model. Use **Test selected** to check a key; the test uses no quota.
2. **Import files…** or **Import folder…**: files are named `doc_1`, `doc_2`, … in import order.
   - The Library cards summarize documents, generated questions, saved questions, and completed Gemini jobs. Use the search box to find a document by name or filename.
3. Tick the documents you want, then click **Generate questions**.
   - Each page is processed separately (at most one Gemini request per page; no request after the document's question budget is exhausted).
   - The app distributes a document-level question budget across its pages. Maximums: 1 page → 5; 2 → 8; 3 → 10; 4 → 12; 5 → 15; more than 5 → 20. Sparse pages may get fewer or none. Gemini receives the current page's limit, and the app enforces the document cap before saving.
   - **Gemini Generated** shows Finished when every page has been processed, or Unfinished while work remains. If the daily quota runs out, pages wait and continue automatically after the reset (midnight Pacific time).
4. **Review questions** opens the View tab: review each generated question and click **Save** to include it in dataset CSV/JSON/JSONL/XLSX. Save opens the next question in the current filtered list when one exists. You can save an unchanged question. **Saved** in the Library shows saved questions out of all generated questions. Actual text edits are marked separately, and the previous version is kept. The Library **View** button opens `workspace/index.html` in your browser; it shows document/page information and saved questions only. The question and reasoning boxes fit their full text by default. Drag the grip below Reasoning steps to make that box taller or shorter; double-click the grip to fit the full text again.
5. To add Gemini chat questions, first import the source PDF/image into this same workspace. Click **Paste Gemini JSON…** in the Library, paste one `gemini_chat_multipage_v1` JSON batch (or load a `.json`/`.txt` file), then **Preview match**. Check the matched `document_id`, filename, page count, and warnings; click **Stage drafts for review**. View opens the matched document. Click each source page to inspect its image and evidence, edit the question/options/reasoning as needed, and click **Save** on each approved question. Staged drafts are stored for recovery but excluded from the dataset files until saved. Re-pasting the same questions skips duplicates. Incomplete JSON is rejected with a line/column error.
5. **Export ZIP…**: choose a folder. The app saves both `bndocvqa_archive_<timestamp>.zip` and an unpacked folder of the same name. Both contain **all current documents and pages**, including unfinished ones, with the readable data files and an offline `index.html` viewer.

If a page fails, its row says so. Click **Generate questions** again to retry only the unfinished pages.

To edit Gemini's instructions, change `page_prompt()` in `bndocvqa/prompts/__init__.py`, increase `PROMPT_VERSION`, save, and restart the app (close and reopen the `.bat` launcher). Finish or cancel queued jobs before changing the prompt if you need a clean version boundary. Existing finished pages are not regenerated automatically. The page-count limits are enforced in code, so changing prompt wording alone cannot raise them. The `QUESTIONS_PER_PAGE` legacy setting no longer controls generation.

**Pages without questions.** Gemini first classifies every page (text, table, form, chart, cover, …). Some pages get no questions:
- blank pages;
- pages with only a QR code or barcode;
- pages with only signatures or stamps;
- pages with only a photo or logo;
- unreadable pages;
- pages Gemini refuses for safety reasons.

The app enforces this itself, not just through the prompt. These pages still count as processed. The View tab shows why a page has no generated questions; the HTML viewer shows page details and notes when there are no saved questions.

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
python -m bndocvqa evaluate D:\exports\bndocvqa_archive_...\questions.jsonl predictions.jsonl
```

## Where things are stored

- `workspace/documents/` holds read-only copies of imported PDFs/images; `workspace/images/` holds rendered page images. Removed documents go to `workspace/trash/`. Existing `originals/` and `pages/` files are copied into this layout automatically on startup; the old files are left in place as a backup.
- `workspace/data/` contains `state.json` and a JSON and CSV file for **every SQLite table**, including generated drafts, saved questions, options, edit history, jobs and request usage. This is a complete recovery snapshot. The top-level `workspace/questions.json`, `questions.jsonl` and `questions.csv` contain **only questions manually saved in the View tab**. `workspace/index.html` shows document/page information and those saved questions only. These files update after changes, and are flushed on app close and export.
- SQLite remains the app's working transaction and job-queue database (`workspace/bndocvqa.sqlite`). If that database is missing, the app rebuilds it from `workspace/data/state.json` when the media folders are present. Edit questions in the app; manually editing CSV/JSON while the database exists does not change app state.
- API keys added in the app use Windows Credential Manager when available. `~/.bndocvqa/keys.json` holds labels/projects; if no credential store is available, it may also contain keys. Keys can come from a `.env` file instead (see `.env.example`). Neither the key store nor `.env` is included in the ZIP.
- The complete ZIP contains `documents/`, `images/`, `data/`, saved-only `questions.json`/JSONL/CSV/XLSX, `index.html` and a SHA-256 manifest. `data/` still contains every draft for recovery. Keep this archive private when the documents or questions are private.

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
Run Bangla DocVQA Builder.bat  one-click Windows launcher
```

This repository builds on the original
[Bangla-DocVQA-dataset-builder](https://github.com/Sazzad14802/Bangla-DocVQA-dataset-builder).
Documents, page images, generated questions, API keys, and exports are local
data and are not included in this repository.

## Tests

```bash
python -m pytest
```

The tests use a mocked Gemini, so they need no network access and no API key.

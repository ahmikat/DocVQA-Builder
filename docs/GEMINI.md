# Gemini: keys, model, quotas

## Keys and model

Click **Gemini API keys…** in the Library to add, remove and test keys, and to pick the model.

- On Windows, keys use Credential Manager when available. Their names and projects are written to `~/.bndocvqa/keys.json`; if the credential store is unavailable, that file can contain the keys themselves. API keys are excluded from workspace archives. Protect `.env` and `keys.json` if you use the fallback.
- Tag each key with its **Google Cloud project**. Quota belongs to the project, not the key, so several keys in the same project share one quota. Adding keys to one project never makes processing faster. If you leave the project empty, the key is treated as its own project.

### Several keys: what happens when one runs out

- **Daily quota used up** (the app's own count, or Google answering "per day" 429): that project is skipped until the reset, and the same request goes straight to the next project's key. Pages only wait until tomorrow when *every* project is out.
- **Per-minute limit hit** (429): the request moves to another project with capacity right away. If there is none, it waits the delay Google suggests.
- **Key invalid, expired, revoked or reported as leaked:** that key is switched off for the session, and the request is retried with another key.
- **Several projects run in parallel.** Each adds its own 15/minute and daily quota.
- Keys in a `.env` file (`GEMINI_API_KEY`, or `GEMINI_API_KEY_1` with `GEMINI_PROJECT_1`, …) also work and are listed in the same dialog.

Page images leave your computer only when you tick documents and click **Generate questions**. They are sent to Google's Gemini API, so make sure you're allowed to share the documents you process.

## Requests and quotas

- **At most one request per page.** A 4-page PDF normally uses 4 requests; pages reached after the document's question budget is exhausted are marked done without a Gemini request.
- **Built-in limits per Google Cloud project:** `gemini-3.5-flash-lite` 15/minute and 500/day; `gemini-3.8-flash` 15/minute and 20/day. Requests are counted in the database, so the count survives restarts, and it resets at midnight Pacific time, like Google's quota.
- **When the daily limit is reached,** the remaining pages wait (the Library shows "⏸ Waiting for daily quota") and continue after the reset. Waiting doesn't use up retry attempts.
- **Per minute:** never more than 15 requests start in any 60 seconds, per project. Up to 3 requests run at once (`GEMINI_CONCURRENCY`), which is about what it takes to reach 15/minute when a page takes several seconds. 500 pages therefore take about 35 minutes on one project. Keys in other projects add their own 15/minute.
- **If Google still answers "too many requests" (429),** the app waits the delay Google suggests (or 30 seconds) and retries. These waits don't count against the page's retry attempts.
- **Other limits:** you can override or add them in `.env` with `GEMINI_MODEL_LIMITS=model=rpm/rpd, …`.

## Reliability

- **Retries.** Temporary errors (server errors, timeouts, malformed JSON) are retried with exponential backoff, up to `GEMINI_MAX_ATTEMPTS` (default 4). After that, the page is marked failed, and **Generate questions** retries it.
- **No duplicates.** Each page's result replaces that page's questions in one transaction, so a retried page never produces duplicates.
- **Restarts.** Pages still queued when you close the app resume automatically next time it opens.

## Prompt

The prompt is in [bndocvqa/prompts/__init__.py](../bndocvqa/prompts/__init__.py). Edit `page_prompt()`, bump `PROMPT_VERSION`, save, and restart the app to load it. Finish or cancel queued jobs before editing when you need a clean version boundary. Finished pages are not regenerated automatically. The page-count cap is enforced by [question_limits.py](../bndocvqa/services/question_limits.py) and the pipeline, so a prompt change cannot override it. `QUESTIONS_PER_PAGE` is a legacy setting and no longer controls generation.

Maximum generated questions per document: **1 page: 5; 2 pages: 8; 3 pages: 10; 4 pages: 12; 5 pages: 15; more than 5 pages: 20**. The remaining budget is shared across unfinished pages, and sparse pages may return fewer questions. Existing questions above a new cap are preserved; this rule applies to future generation.

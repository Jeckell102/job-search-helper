# Job Search v3.3 — ChatGPT Pro / Work Workflow

The local helper is now scraper-only. It makes no OpenAI API calls.

## Local command

```bash
./job-search-scraper start
```

`./job-search-reviewer start` remains as a compatibility alias, but it also starts only the scraper.

The scraper:
- resumes an unfinished cycle automatically;
- otherwise starts a new full-company cycle;
- writes all discovered jobs to Google Sheets Job History;
- automatically rejects clear title families and clear maximum base salary below $120,000;
- marks surviving new/materially changed jobs `Needs Review`;
- keeps `.state` only for scan/cycle recovery.

## ChatGPT Work reviewer

Use ChatGPT Work on web or desktop with your Google Drive connection. Work can edit native Google Sheets when the Google Drive app is connected and authorized.

1. Open **Work** in ChatGPT.
2. Select **GPT-5.6 Sol** for the review task if available.
3. Make sure Google Drive is connected to the Google account that owns/has edit access to `Job Search Master - Companies & Opportunities`.
4. Attach or @mention that Sheet.
5. Paste the contents of `prompts/WORK-JOB-REVIEWER.txt`.
6. Start the Work task after the scraper has built some backlog. The prompt tells Work to process one job at a time until the scan is complete and the queue is drained.

This uses your ChatGPT plan's Work allowance rather than OpenAI API billing. No `OPENAI_API_KEY` is used by the helper.

## New Job History columns

v3.3 adds and backfills:
- Source Hash
- Salary / Range
- Work Arrangement
- Job Description (pointer only; full text is in Job Evidence)

The `Job Evidence` tab stores full descriptions by `Job Key` + `Source Hash`. `Source Hash` is the current scraper evidence hash. When Work completes a substantive review, it copies `Source Hash` to `Description Hash`, making that source version the reviewed baseline.

## Concurrency

Work claims a row by setting `Review Status = In Progress` and `Review Started At`. The scraper skips an `In Progress` row entirely for that scan pass, including Last Checked / Last Seen updates, then sees it normally in a future scan after the lock clears.

# Automated Job Search — v3.3 ChatGPT Pro / Work

The local helper is scraper-only and makes no OpenAI API calls.

Normal scraper command:

```bash
./job-search-scraper start
```

The scraper resumes the newest unfinished scan cycle. If none exists, it starts a new full-company scan.

Google Sheets is the durable source of truth. `.state` stores only scan/cycle recovery data.

## Scraper path

1. Retrieve complete official ATS inventory where supported.
2. Match jobs against Job History by stable identity.
3. Skip an `In Progress` row so ChatGPT Work owns its review snapshot.
4. New jobs receive deterministic $0 screening:
   - obvious excluded title -> `Reviewed / Reject` directly;
   - clear maximum annual USD base below $120,000 -> `Reviewed / Reject` directly;
   - otherwise -> `Needs Review`.
5. Materially changed previously reviewed jobs return to `Needs Review`.
6. Work-readable source fields are written directly into Job History.

## ChatGPT Work

Use `prompts/WORK-JOB-REVIEWER.txt` in ChatGPT Work with the connected Google Drive Sheet. Work reviews one `Needs Review` row at a time and writes decisions directly back to Job History / Opportunities.

No API key, OpenAI SDK, local AI queue, or local decision file is used.

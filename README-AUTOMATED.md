# Automated Job Search — v3.3 ChatGPT Pro / Work

The local helper is scraper-only and makes no OpenAI API calls.

Normal scraper command:

```bash
./job-search-scraper start
```

The scraper resumes the newest unfinished scan cycle. If none exists, it starts a new full-company scan.

Parallel fetchers can retrieve company inventories while one writer controls all Google Sheets updates:

```bash
./job-search-scraper start --fetch-workers 4 --assignment-window 25
```

The controller preloads the local assignment queue. Fetchers return their results to a bounded local buffer and take another company without waiting for Sheets writes. Only the writer touches Sheets or SQLite. The assignment window bounds unsaved company work (plus the company being saved) and is at least the worker count. Fetchers can idle if the buffer is full or eligible work runs out; Companies sheet status can lag actual activity during a write.

Blocked/failed/partial scans record the actual adapter in `ATS / Source` when known. Unknown discovery leaves the existing source unchanged, and blocked scans do not advance successful-scan dates. Ctrl+C cancels unstarted assignments; unfinished companies resume by refetching without duplicate saved jobs.

To tune Google Sheets pacing for the writer:

```bash
./job-search-scraper start --fetch-workers 4 --assignment-window 25 --sheet-request-interval 1.1
```

Use `./job-search-scraper help` to see the current options.

To apply the current title blacklist to existing Job History rows:

```bash
./job-search-scraper cleanup-blacklist
```

Use `./job-search-scraper cleanup-blacklist --dry-run` only when you want a preview.

Google Sheets is the durable source of truth. `.state` stores only scan/cycle recovery data.

## Scraper path

1. Retrieve complete official ATS inventory where supported.
2. Match jobs against Job History by stable identity.
3. Skip an `In Progress` row so ChatGPT Work owns its review snapshot.
4. New jobs receive deterministic $0 screening:
   - blacklisted title -> skipped, with a terminal reason;
   - clear maximum annual USD base below $120,000, travel above 50%, nonpermanent employment, or explicit SaaS product responsibilities -> `Reviewed / Reject` directly;
   - otherwise -> `Needs Review`.
5. Materially changed previously reviewed jobs return to `Needs Review`.
6. Work-readable source fields are written directly into Job History.

## ChatGPT Work

Use `prompts/WORK-JOB-REVIEWER.txt` in ChatGPT Work with the connected Google Drive Sheet. Work reviews one `Needs Review` row at a time and writes decisions directly back to Job History / Opportunities.

No API key, OpenAI SDK, local AI queue, or local decision file is used.

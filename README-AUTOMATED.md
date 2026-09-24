# Automated Job Search — v3.3 ChatGPT Pro / Work

The local helper is scraper-only and makes no OpenAI API calls.

Normal scraper command:

```bash
./job-search-scraper start
```

The scraper resumes the newest unfinished scan cycle. If none exists, it starts a new full-company scan. By default it starts `5` fetch workers, `--assignment-window 100`, `--batch-size 200`, one Google Sheets writer, and the terminal dashboard.

Parallel fetchers can retrieve company inventories while one writer controls all Google Sheets updates:

```bash
./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200
```

The controller preloads the local assignment queue. Fetchers return their results to a bounded local buffer and take another company without waiting for Sheets writes. Fetchers commit complete inventories to a durable SQLite inbox before taking another assignment. Only the controller accesses Sheets and cycle checkpoints. The assignment window bounds unsaved company work (plus the company being saved) and is at least the worker count. Fetchers can idle if the buffer is full or eligible work runs out; Companies sheet status can lag actual activity during a write.

The dashboard gives each worker a persistent color-coded row with its current company. The green writer row shows save progress, duration, and the run total after completed Sheets batches. The left `Workers` list records every worker handoff to the writer; the right `Jobs` list records confirmed new Job History rows after they are written to Google Sheets, clipping long job titles with `...`.

Company-specific writer errors are logged to `.state/scraper-errors.jsonl`, marked `Blocked / Manual Review` in Companies, and the scraper keeps moving. Use `./job-search-scraper errors` to review recent failures.

Supported public boards are Greenhouse, Lever, Ashby, Workday, iCIMS, ADP Workforce Now, Paylocity, and Taleo. Dayforce remains manual unless discovery finds a supported board link. Blocked/failed/partial scans record the actual adapter in `ATS / Source` when known. Unknown discovery leaves the existing source unchanged, and blocked scans do not advance successful-scan dates. Ctrl+C cancels unstarted assignments. Completed fetches are retained in SQLite, and restart replays saved inventories without duplicate rows; fetches without saved results are repeated.

To tune Google Sheets pacing for the writer:

```bash
./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200 --sheet-request-interval 1.1
```

Use `./job-search-scraper help` to see the current options.

To apply the current title blacklist to existing Job History rows:

```bash
./job-search-scraper cleanup-blacklist
```

Use `./job-search-scraper cleanup-blacklist --dry-run` only when you want a preview.

Google Sheets holds synchronized job records and review decisions. Full descriptions live in the `Job Evidence` tab, keyed by `Job Key` + `Source Hash`; Job History keeps only a short pointer so filtering remains usable. Run `./job-search-scraper setup-evidence-tab --apply --exclusive-writer` once before starting after this schema change.

Google Sheets holds synchronized job records and review decisions. `.state/inventories.sqlite3` durably holds full fetched inventories until their Sheets writes and company checkpoints succeed. Keep `.state`, including SQLite WAL files, to preserve unsynced jobs. Failed company writes retain their payloads.

To fetch now and sync job rows later in a separate process invocation:

```bash
./job-search-scraper start --defer-sync
./job-search-scraper sync
./job-search-scraper performance
```

The deferred run still updates company/cycle control records. `sync` does not fetch job boards. After fixing a company write error, use `sync --retry-blocked`; use `start --retry-blocked` for failed fetches. You can also change a blocked company's `Scan State` back to `Queued` in Sheets before starting; startup refreshes company controls and treats that row as an explicit retry signal for the saved local blocked entry. Commands share the exclusive writer lock and should run sequentially. Normal `start` automatically saves locally and syncs while other workers fetch. Request pacing and read backoff are unchanged.

The writer reuses indexed planning data, reads only identity columns/affected rows on subsequent large-tab commits, and groups new rows into bulk writes. User edits, formulas, validation, blacklist rules, and manual exclusions remain protected. [Offline measurements and test results](docs/writer-performance.md) describe the measured improvement; no live speedup is claimed.

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

Use `prompts/WORK-JOB-REVIEWER.txt` in ChatGPT Work with the connected Google Drive Sheet. Work reviews one `Needs Review` row at a time and writes decisions directly back to Job History / Job Evidence / Opportunities.

No API key, OpenAI SDK, local AI queue, or local decision file is used.

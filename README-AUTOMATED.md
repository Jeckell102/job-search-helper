# Automated Job Search — v3.3 ChatGPT Pro / Work

The local helper is scraper-only and makes no OpenAI API calls.

## SQLite and Sheets synchronization

With local SQLite storage, `./job-search-helper start` owns the complete Sheets
sync lifecycle. No separate always-running Sheets service is required:

1. When Sheets is available, pull current company controls and manual edits
   into SQLite before publishing.
2. Publish pending local changes from earlier work before choosing companies,
   using one sync interval (60 seconds by default) / 20 batches as a budget.
   Any remaining backlog stays saved and continues publishing during the run.
3. Scrape locally, check for saved updates every two seconds, and publish
   pending batches continuously. Idle checks make no Google requests. Each
   write retains fresh identity and expected-value guards for manual edits.
4. On normal completion or a handled interruption, make a final publish and
   stop the sync worker before the command exits.

If a reviewer is publishing to Sheets at startup, scraping starts immediately
using the saved local company controls. Only Sheets intake and publication defer;
the background worker retries every five seconds while the writer is busy. The
shared Sheets lock covers active sync work and is released between updates, so
review publication can run during a scrape. A busy writer at exit leaves changes
saved locally for the next sync without failing the scrape. Deferred intake
refreshes company controls and manual edits before publishing anything. A second
scraper still fails immediately on the separate scraper lock.

Startup reports progress after each batch. Reaching its publishing budget, or
finding no further safely publishable work, does not prevent scraping; dirty
cells and reconciliation protections remain intact. Actual intake or delivery
errors during an immediate startup sync still stop startup; writer contention
only defers synchronization. Final publishing uses a five-minute /
1,000-batch budget and reports an incomplete sync if any work remains, including
why the drain stopped. Time budgets are checked between batches; an in-flight
batch is allowed to finish normally and may exceed the budget. Periodic failures
do not discard local work. A forced kill cannot perform a final network request;
the next normal start reconciles saved delivery state.

The end-of-run summary separates the invocation ending from the scan cycle's
status, lists company stages, and labels review counts as all of Job History.
An `In Progress` cycle still has unattempted or unstaged company work. A finished
pass with incomplete inventories is `Complete with exceptions`; failed browser
discovery stays partial and does not keep the scan open indefinitely. Pending AI
reviews alone do not prevent a completed scrape. The final summary appears after
Sheets cleanup and performance output. It reports new Job History rows added by
this invocation, companies successfully scanned, partially scanned, and skipped
within its scope (blank when zero). Blocked/failed and saved-but-unprocessed
counts appear separately when nonzero. Existing jobs and updates are not new
jobs; title-blacklist entries retained only in the local audit are not counted. Review queue output explicitly
reports title-audit overlap: those records appear in both FIRST PASS and the
filtered audit. `filtered_only` excludes that overlap.

Performance is saved after the final queue refresh and Sheets drain. The
`sheets_published_row_updates` and `sheets_publish_batches` totals include
startup backlog, every periodic update, and the final drain. Row updates are
not unique rows or new jobs. `sync_batches` counts local pipeline commits when
using SQLite, not Sheets publish batches. `checkpoint_payload_bytes` is the
cumulative serialized checkpoint/inventory/plan payload, not one checkpoint's
size. These totals cannot be reconstructed for earlier runs from their last
periodic log line.

The previous `job-search-sync.service` should be disabled, along with its expiry
timer, so it cannot compete for the single Sheets-writer lock. An explicitly
requested one-shot storage sync remains available for maintenance. Normal reviewer submissions publish their saved review outcomes to Sheets immediately,
including while the scraper is stopped. Reviewer publication uses the same writer
lock and guarded field-level synchronizer, scoped to the saved review and required
Opportunity; it does not publish unrelated scraper changes. Local saves and verified
Sheets delivery have separate durable receipts. No idle service is required.

`./job-search-reviewer publish --pass N --limit 100` retries a bounded batch of
saved reviews, including results saved before automatic publication was added,
without starting a review or taking claims. Add `--run-id RUN_ID` to restrict it
to one worker. Normal submit, writeback, and finish also attempt publication.
A failed or busy publisher retains the saved outcome for retry; finish cannot
report drained while required remote publication is pending. `--local-only` keeps
an explicitly output-only submission staged without publishing.

`start --defer-sync` intentionally stays local-only with SQLite: no startup
pull, authentication, periodic publish, or final Sheets publish. A later
`./job-search-scraper sync` stages saved inventories and uses the run-scoped
Sheets lifecycle without fetching companies.

Every normal `start` creates a fresh full-company scan. An explicitly prepared
`.state/next-scan.json` request can additionally supply ordering and comparison metadata. Its unique request ID and
receipt (`last-scan-request.json`) prevent repeated creation after interruption.
The new cycle records which old cycles it supersedes; old companies, inventories,
browser checkpoints, errors and scan records remain stored unchanged. They are
not silently marked complete or replayed by a normal subsequent start. Specific
company IDs in `start_last` are assigned after the other eligible companies,
not excluded. If the new run is interrupted, `start --resume` resumes that run.
A pending fresh request conflicts with `--resume` and remains intact for a
normal `start`. Old saved inventories can still be processed with `sync`.

Normal scraper command:

```bash
./job-search-scraper start
```

The scraper starts a fresh scan of all currently active companies, including companies completed or partial in prior scans and companies added since the last scan. `./job-search-helper start --resume --fetch-workers 15` explicitly continues the latest scan, skips its completed companies, and retries partial inventories using saved browser progress. It never falls back to an older unfinished scan or silently creates a new one. Blocked retries follow `--retry-blocked` / `--no-retry-blocked`. By default it starts `5` fetch workers, `--assignment-window 100`, `--batch-size 200`, one Google Sheets writer, and the terminal dashboard.

Parallel fetchers can retrieve company inventories while one writer controls all Google Sheets updates:

```bash
./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200
```

The controller preloads the local assignment queue. Fetchers return their results to a bounded local buffer and take another company without waiting for Sheets writes. Fetchers commit complete inventories to a durable SQLite inbox before taking another assignment. Only the controller accesses Sheets and cycle checkpoints. The assignment window bounds unsaved company work (plus the company being saved) and is at least the worker count. Fetchers can idle if the buffer is full or eligible work runs out; Companies sheet status can lag actual activity during a write.

The dashboard gives each worker a persistent color-coded row with its current company. The green writer row shows save progress, duration, and the run total after completed Sheets batches. The left `Workers` list records every worker handoff to the writer; the right `Jobs` list records confirmed new Job History rows after they are written to Google Sheets, clipping long job titles with `...`.

Company-specific writer errors are logged to `.state/scraper-errors.jsonl`, marked `Blocked / Manual Review` in Companies, and the scraper keeps moving. Use `./job-search-scraper errors` to review recent failures.

Supported public boards are Greenhouse, Lever, Ashby, Workday, iCIMS, ADP Workforce Now, Paylocity, and Taleo. Dayforce remains manual unless discovery finds a supported board link. Blocked/failed/partial scans record the actual adapter in `ATS / Source` when known. Unknown discovery leaves the existing source unchanged, and blocked scans do not advance successful-scan dates. Ctrl+C cancels unstarted assignments. Completed fetches are retained in SQLite, and `start --resume` replays saved inventories without duplicate rows; fetches without saved results are repeated. Plain `start` begins a fresh scan.

Optional browser fallback: install `.[browser]` and Chromium with Playwright, then run `./job-search-scraper start`. Direct adapters still run first. The fallback is enabled by default, opens the public careers page, captures same-site JSON responses, scrapes visible job links/details, and returns normal inventory rows when complete. It does not bypass login, CAPTCHA, or access controls; failures stay incomplete/manual-review. Use `--no-browser-fallback` for direct-adapter-only runs.

Generic browser detail fetching waits for a usable title and description, rather than waiting for background network traffic to stop. A timeout triggers a final content check; an unreadable detail page stays unresolved instead of receiving listing-page text as its description. Detail pages close after every attempt, including failures. Fetching remains sequential within each company.

Confirmed navigation pages (such as testimonials, facilities, and candidate
resources) are excluded from both new discovery and resumed browser retries.
Original checkpoints remain stored for audit. Generic inventory coverage stays
partial; excluding navigation does not establish that any posting closed.
ADP MyJobs uses individual `/cx/job-details?reqId=...` links. Legacy saved
inventories containing only board links are normalized before planning without
changing posting IDs, descriptions, or already frozen operations.

The automated runner checkpoints discovered URLs, each successful description, and listing-page progress in `.state/inventories.sqlite3`, scoped to the cycle, company, and careers URL. It retries unresolved details once after the first pass. Remaining failures are reported as partial, so a completed pass closes with exceptions. Run `./job-search-helper start --resume` to resume unfinished discovery and detail URLs without refetching saved descriptions, or normal `start` to freshly check every active company. A new cycle refreshes the jobs. Keep the entire `.state` directory. Generic browser coverage remains partial even when all discovered URLs are read: unknown coverage and failed pages never establish that a job closed. Running processes load these changes on their next restart; older in-flight fetches have no per-job checkpoint yet.

Phenom fetches continue after individual closed, edited, or unreadable postings.
They compare every listing page and allow up to three reconciliation retries.
Completion requires two matching full inventories, unchanged employer scope,
unique posting identities, and validated details for every current posting.
Unresolved details or listing drift keep coverage partial; access denials and
rate limits stop the fetch. A missing detail alone never establishes closure.

Phenom details are checkpointed individually in the same SQLite inbox, isolated
by cycle, company, and configured source. A retry rereads the listing and reuses
only details whose listing identity and revision still match. Edited postings
are fetched again. These checkpoints use separate records from generic browser
URL queues. A partial result is retried by `start --resume`; normal `start` creates a fresh
scan with new per-cycle checkpoints.

TalentBrew collects the full listing before reading details, then reconciles all
pages by posting identity and title rather than display order. Closed, edited,
or malformed individual postings do not stop unrelated details. At most three
reconciliation retries follow the initial pass; unresolved jobs or inconsistent
listings keep coverage incomplete. Access denials and rate limits stop fetching.

TalentBrew checkpoints successful details separately from generic browser queues
in the SQLite inbox, scoped to the cycle, company, and discovered board URL.
Retries reuse matching saved details, refresh edits, and retire cached details
only after confirmed stable absence. Diagnostics include the stage, page, posting
ID, advertised count, and retained count. Browser pages wait for usable results
instead of network idleness; verified L3Harris details use the public HTML page.
Boeing Defense, Space & Security still requires a verified division feed; its
unfiltered parent board is explicitly unsupported for that company row.

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

The deferred run still updates company/cycle control records. `sync` does not fetch job boards. After fixing a company write error, use `sync`; use `start` for failed fetches. Blocked saved work is retried by default; pass `--no-retry-blocked` to skip it. You can also change a blocked company's `Scan State` back to `Queued` in Sheets before starting; startup refreshes company controls and treats that row as an explicit retry signal for the saved local blocked entry. Commands share the exclusive writer lock and should run sequentially. Normal `start` automatically saves locally and syncs while other workers fetch. Request pacing and read backoff are unchanged.

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


Nuro is routed from its exact configured careers URL to the public Greenhouse
feed used by Nuro's own careers-page scripts. It retrieves full job descriptions
with stable posting IDs instead of opening each custom `careersitem` wrapper.
Changed company names, IDs, or filtered careers URLs bypass this curated repair.

Generic browser fallback has a five-minute budget per company invocation,
including listing discovery and detail attempts. Each detail pass stops after
five consecutive failures; a shorter first pass still gets a longer retry so
slow pages can recover. Successful descriptions reset the failure count and
remain checkpointed. The budget limits each next navigation/detail timeout;
unfinished discovery and detail URLs remain partial and resumable. Known local
detail errors now include a reason, rather than only the exception class.


SQLite Sheets publication checks for saved changes every two seconds without
making idle Google requests. After a publishing pass makes progress with work
remaining, the next pass starts immediately; the shared Sheet-writer lock is
released between passes. Held work, writer contention, and errors retain their
existing retry delays. `--sync-interval` still controls local partial-batch and
cycle checkpoints and bounds a publishing pass; it no longer adds a fixed pause
after a successful pass with a backlog.

Existing-row batches reuse prior identity locations only to select affected
ranges. The write still reads all live identities, manual controls, and affected
cell metadata together in one fresh response. A moved row or changed layout falls back to fresh discovery; manual controls
are read freshly for every affected row and duplicates still block writing.
Stable successive batches therefore avoid a redundant whole-tab identity read.

Only stable identity columns are scanned across the full Job History tab;
`Added to Opportunities?` and `Review Status` are freshly read for affected rows.
An offline 3,000-row benchmark reduced the second batch from two reads to one
and reduced its response payload by 76%, while preserving target-row metadata.

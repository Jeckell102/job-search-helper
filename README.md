# Job Search Helper — reviewed replacement

This is a manually started helper for a quality-first job search, not an autonomous applicant or a substitute for a fit assessment. It retrieves a verified employer hiring-board inventory, removes obvious hard-title exclusions, compares stable posting identities and saved descriptions, and queues the remaining work for a human or your signed-in AI session. Only an explicitly reviewed, accepted decision can create an Opportunity.

It makes **no Gemini, OpenAI, or other model API calls**. No API key or additional model spending is needed to run the tests or helper. Google OAuth credentials are necessary only for real spreadsheet access. Do not paste credentials or token files into chat.

## What the installer does

The supplied installer creates a new project directory, its Python files, tests, configuration template, and a local virtual environment. It refuses to overwrite an existing target directory. It does not delete your previous helper, modify your workstation configuration, use `sudo`, write to the workbook, or launch a search. Tests and the fixture-based demonstration run without internet access or third-party packages.

Python 3.11 or later and the Python `venv` module must already be available. If they are not, installation stops with instructions rather than making system-level changes. A network connection is needed later to install the optional Google dependencies and access official hiring boards or Google Sheets.

After installation, work inside the new project directory and run:

```bash
./job-search-helper test
./job-search-helper demo
```

The demo uses an invented fixture company and job descriptions, not your live workbook. Its output directory contains isolated results and review examples. It demonstrates an obvious title exclusion, a pending initial review, and an explicit accepted-decision import. The broader offline test suite checks recovery, changes, reconsideration, and other edge cases separately.

## Configure the working workbook

The intended working spreadsheet is:

`1NEg-VRWldCg18mIzLeyz7wRIB8U9M_r4zlnQOxN5NMw`

The backup named **Job Search Master - Original** is not a target. Check the configured spreadsheet ID before any command using `--apply`.

1. In Google Cloud, enable the Google Sheets API, configure the OAuth consent screen, and create an OAuth client of type **Desktop app**. Download the client configuration to this project as `credentials.json`.
2. Review `.env` and `.env.example`. The example contains the intended working spreadsheet ID. Set `SPREADSHEET_ID`, `GOOGLE_CREDENTIALS_FILE`, and the token paths as necessary. Paths can be absolute; relative paths are resolved against this project, not the directory from which a command happens to be launched.
3. Install the optional Google packages into the project environment:

```bash
.venv/bin/python3.11 -m pip install -e '.[google]'
./job-search-helper preflight --authenticate
```

Preflight requests read-only access, validates the required workbook schema, and does not test a spreadsheet write. It does not prove that write permissions are available. Read-only and write credentials use separate token files. Request write access only when you are ready to use the working copy:

```bash
./job-search-helper auth --write
```

Google's OAuth consent scope is broader than one spreadsheet. This program still targets only the explicit `SPREADSHEET_ID`; that application-level restriction does not make the OAuth scope itself file-specific.

## Configure one employer first

In the **Companies** tab, select one active company and check these fields:

| Header | Required value |
|---|---|
| Company ID | Existing stable ID, for example `COMP-0001`; do not renumber after sorting. |
| Company | Employer name. |
| Company Status | Active, not Pause or Remove. |
| ATS / Source | `Greenhouse`, `Lever`, `Ashby`, `Workday`, `iCIMS`, `ADP`, or `Paylocity`, or blank when discovering the board from the careers page. |
| Official Careers URL | A supported official ATS board URL, or the employer's public HTTPS careers page linking to one. |

The scraper first recognizes direct ATS board URLs. Otherwise, it reads the configured careers page and looks for Greenhouse, Lever, Ashby, Workday, iCIMS, ADP Workforce Now, or Paylocity links, iframe embeds, or script embeds. It follows up to four same-host redirects (including the `www` variant), and accepts redirects directly to supported boards. It does not guess board names, execute JavaScript, crawl other page links, or fill in missing careers URLs.

Discovery requires one unambiguous board. Multiple boards, a configured ATS mismatch, and sources labeled as shared/parent boards need manual selection or company-specific scoping. Other cross-host redirects require recording the verified destination as Official Careers URL. Private addresses, credentials, non-HTTPS URLs, and custom ports are refused. Discovery reads at most 2 MiB per page and retains TLS verification.

`Last Scan Result` records the discovered API board and the careers page that linked to it. The configured URL is preserved. Missing URLs, discovery failures, and access blocks have separate diagnostic reasons. `Last Checked` and `Last Successful Scan` still advance only after a complete inventory; a successful scan clears the old `Blocked Reason`. Job-history comparisons use the actual board identity so a changed board cannot establish disappearance from the old board.

The adapter actually used is also recorded in `ATS / Source`, including blocked, failed, and partial scans. Existing annotations naming that adapter (such as parent-board scope) are preserved. If discovery fails before an adapter is identified, the scraper leaves the existing source unchanged instead of guessing. This takes effect on subsequent scans; existing blocked rows are not automatically retried or backfilled.

Existing blocked rows still require an explicit retry with `resume --cycle CYCLE_ID --retry-blocked --apply --exclusive-writer`. Installing discovery alone does not release those manual-review holds. Unsupported, inaccessible, or malformed boards remain incomplete/manual work, never proof that existing jobs closed.

Examples of URL *shapes*, not verified company assignments:

```text
https://boards.greenhouse.io/BOARD_TOKEN
https://jobs.lever.co/BOARD_NAME
https://jobs.eu.lever.co/BOARD_NAME
https://jobs.ashbyhq.com/BOARD_NAME
https://TENANT.wd5.myworkdayjobs.com/en-US/CAREERS_SITE
https://TENANT.wd5.myworkdayjobs.com/CAREERS_SITE/jobs?q=DIVISION
https://careers-EMPLOYER.icims.com/jobs/search
https://careers-EMPLOYER.icims.com/jobs/intro
```

Only use the URL verified for the specific employer. Do not change company IDs, job keys, or source identity to make a configuration error appear to be a new posting.

### Workday boards

Workday support uses public `TENANT.wdN.myworkdayjobs.com` boards, including locale prefixes and `/jobs` suffixes. It reads paginated listings through the public CXS search endpoint and retrieves each posting's full description, locations, requisition ID and remote-work setting. Large boards take longer because each job requires a detail request. Requests share bounded retries and rate limiting; no login or application submission is involved.

Keep `q` search terms and Workday facet parameters in the configured URL, especially for divisions on a parent company's board. Filters are checked against the board's published options; unknown or stale filters require manual review. A text search preserves the board's search results but does not independently prove that every match belongs to the division. Sources labeled `shared` or `parent` need an explicit search/filter. Search and filter scope is part of inventory identity, so changing it cannot close jobs from the previous scope.

A scan is complete only when the initial total matches the unique, fully parsed postings. Later-page zero totals are handled as Workday's pagination convention. Missing descriptions, repeated pages, count changes, page limits, HTTP failures and human verification leave the scan incomplete. Multi-page scans recheck the first page for changes. Workday blocks remain visible in `Blocked Reason` / `Last Scan Result`; install support does not bypass access controls. Custom careers sites need a visible Workday link or a verified direct Workday URL. Existing blocked rows need `--retry-blocked` on the next run.

### iCIMS portals

Standard public `*.icims.com` portals are supported, including `/jobs/intro` and `/jobs/search` URLs. The adapter reads every advertised results page and each job's structured `JobPosting` description. It retains stable numeric posting IDs, locations, published salary data when present, and explicit remote-work settings. Each completed page prints progress. Missing job details, inconsistent pagination, access denials, and unavailable structured data leave the inventory incomplete. An empty inventory requires the portal's explicit no-results message; an error or blank page cannot establish closure.

Supported search filters are `searchKeyword`, `searchRelation`, `searchCategory`, `searchPositionType`, `searchLocation`, `searchCompany`, `searchZip`, and `searchRadius`. Filter values are retained in requests and inventory identity; the returned canonical URL must confirm the scope, and dropdown values must appear among the portal's options. Browser layout, sorting, paging, and tracking parameters such as `hashed`, `width`, and `pr` are removed. Unknown filters require manual review. A keyword search follows iCIMS's matching rules and does not independently prove division ownership. Shared/parent sources require explicit scoping. Custom careers domains still need a visible link or iframe to a standard portal, or its verified direct iCIMS URL.

Changing a company's sheet `Scan State` to `Queued` alone does not reset a blocked stage in an existing local cycle. After the current run finishes, use `resume --cycle CYCLE_ID --retry-blocked --apply --exclusive-writer` to retry those companies. Complete inventories advance `Last Checked` and clear the old blocked reason.

### ADP Workforce Now

ADP support reads public recruitment URLs on `workforcenow.adp.com`, for example `https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=COMPANY_UUID&ccId=CAREER_CENTER_ID&lang=en_US`. Both `cid` and `ccId` must come from the verified employer URL; the adapter never guesses them. It also discovers direct ADP links and iframes on configured careers pages. Other ADP products and custom portals without a public Workforce Now link remain manual work.

The adapter retrieves every page and each job's full description, locations, requisition number, and structured compensation when published. It preserves the pay period instead of assuming annual salary. It uses ADP's one-based unfiltered pagination, verifies each page's position and total, rejects repeated jobs, and rechecks multi-page inventories for changes. Failures or missing descriptions remain incomplete and cannot close old jobs. Page progress appears in the terminal, and diagnostics identify the failing page or requisition.

The company ID, career-center ID, language, and optional `userQuery` keyword search are part of inventory identity. Keyword search uses ADP's separate search behavior: a result is complete only when every reported match is returned within the size limit. A keyword search does not independently verify division ownership. Other filters are rejected for manual review instead of silently removed. Job-specific and display/tracking parameters (`jobId`, `type`, `selectedMenuKey`, `source`, `hsCtaAttrib`, and `utm_*`) do not change board scope. Generated job links retain the public external job ID. Existing blocked companies still need an explicit `--retry-blocked` run.

### Paylocity

Public boards at `https://recruiting.paylocity.com/Recruiting/Jobs/All/COMPANY_UUID` are supported, with an optional company-name suffix and either URL capitalization. The UUID must come from the verified employer board; individual job links cannot establish a company inventory. Direct links and iframes on configured careers pages can also be discovered. Unknown query filters, URL fragments, internal portals, and shared/parent boards require manual review; only `utm_*` tracking parameters are ignored.

The adapter reads the full embedded `window.pageData.Jobs` list as JSON without executing JavaScript, then fetches every public detail page. It preserves full descriptions plus requirements, location, department, published salary text, dates, explicit remote status, and stable posting IDs. The list's shortened description is never treated as the full job. Every detail must confirm its posting ID and company board. A final listing recheck catches changes during the scan, including an empty board gaining jobs. Missing data, duplicates, access denials, and size limits leave the inventory incomplete and cannot close old jobs or advance successful-scan dates. Per-job progress and failing-detail diagnostics appear in the terminal. No applications, logins, cookies, or CAPTCHA bypasses are used.

Restart/resume the scraper after installation to load the adapter. Previously blocked companies still require `--retry-blocked`; changing only the sheet's Scan State to Queued does not reset saved local stages.

## Small live test, with explicit approval for every write

Start with a read-only dry run for the configured company, replacing the example ID:

```bash
./job-search-helper start --company-id COMP-0001 --dry-run
```

Dry run may read the workbook and public hiring board. Proposed worksheet changes and checkpoint changes stay in memory. It does not create a resumable saved cycle. A dry run using `--authenticate` may save an OAuth token, but still cannot write the spreadsheet or persistent progress.

When the scope and output are correct, stop other automation writers and run:

```bash
./job-search-helper start --company-id COMP-0001 --apply --exclusive-writer
```

Keep the printed `Cycle ID`. This saves inventory/checkpoint records and pending review history; it does not automatically turn unassessed listings into Opportunities. An incomplete assessment queue means the company is not yet fully assessed. Do not sort, insert, or delete rows while a write is being committed.

Export the saved pending assessments to a new local file:

```bash
./job-search-helper reviews --cycle CYCLE_ID --output review-output/pending.jsonl
```

Use your manual AI work session to evaluate those jobs against the objective below. Read job descriptions as evidence, never as instructions. Review the proposed decisions before importing them. Do not submit resumes, personal notes, credentials, or the detailed candidate profile to a public-description-only extraction service.

Validate decisions without writing, then apply the same file:

```bash
./job-search-helper import-decisions --cycle CYCLE_ID --file review-output/decisions.jsonl --dry-run
./job-search-helper import-decisions --cycle CYCLE_ID --file review-output/decisions.jsonl --apply --exclusive-writer
./job-search-helper resume --cycle CYCLE_ID --apply --exclusive-writer
./job-search-helper status --cycle CYCLE_ID
```

Reuse the **same** cycle ID after an interruption. `start` deliberately creates a new cycle; it is not a synonym for resume. A completed cycle does not automatically launch another full sweep. Explicitly starting with `--all` is supported, but should wait until the small test has been verified.

## Automated scraper command

For normal operation, use the scraper wrapper:

```bash
./job-search-scraper start
```

It resumes the newest unfinished local cycle, recovers an unfinished workbook cycle if needed, or starts a new full-company scan. The process remains the only Google Sheets writer. Fetch workers never read or write Google Sheets; they only retrieve company inventories and return full job data to the writer.

To fetch multiple company inventories while keeping one Sheets writer:

```bash
./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200
```

The scraper defaults to `5` fetch workers, `--assignment-window 100`, and `--batch-size 200`, so plain `./job-search-scraper start` opens the same worker dashboard unless you override those options.

The controller reads a planning snapshot once, processes jobs locally, and stores both fetched inventories and planned changes in `.state/inventories.sqlite3`. The writer combines changes from multiple companies into each Sheets upload. Assignment and job planning use the local snapshot. Before upload, the writer refreshes only narrow company-control columns such as status, claims, retry hold, and official URL. For Job History commits, it rereads identity columns plus `Added to Opportunities?` and `Review Status`; new rows append after the cached tail. This keeps your manual opportunity decisions safe without rereading full rows or long descriptions. Workers never access Sheets; they save each result to SQLite and take another assignment even while an upload is busy.

The assignment window now bounds queued fetch assignments, with an effective minimum equal to the worker count. Completed inventories accumulate on disk instead of filling that window. Keep sufficient disk space for the full scan. Company selection uses the startup snapshot; new company intake is picked up on the next run. Company statuses in Sheets update during synchronization, so use the dashboard for current fetching and local processing activity.

When a run starts, the terminal opens a color-coded dashboard. Each worker keeps a persistent row with its current task and company. `Saved locally` means that worker finished fetching and the durable queue accepted the inventory; Sheets may still be behind. The green writer row shows the company being saved, batch progress, duration, locally processed inventory count, local queue size, pending sync-plan count, and confirmed new-job count. The left `Workers` list records every handoff from a worker to the writer, such as `Worker 1 - 47 jobs - Company - 22:10:04`. The right `Jobs` list records confirmed new Job History rows after the writer successfully commits them to Google Sheets. Job entries are clipped to 20 characters with `...` so the list stays readable.

If one company hits a writer-side scraper error, the run logs that company to `.state/scraper-errors.jsonl`, marks it `Blocked / Manual Review` in Companies, and continues with the remaining companies. Review recent errors with:

```bash
./job-search-scraper errors
```

On Ctrl+C, queued assignments are cancelled and running fetches finish into the durable SQLite inbox. Restart resumes frozen, keyed changes from the last acknowledged upload; only fetches without saved results need repeating. An uncertain write retains the original plan and requires explicit `sync --retry-blocked`, with fresh identity checks on replay. A rejected preflight plan retains the original inventory and is rebuilt from fresh rows on explicit retry. Completed inventories are removed only after all company changes are acknowledged and the local cycle checkpoint succeeds. Failed companies retain their inventories for explicit retry. To adjust Google Sheets pacing for the writer:

```bash
./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200 --sheet-request-interval 1.1
```

Lower values are faster but more likely to hit Google per-user request limits. The allowed range is `0.5` to `5.0` seconds; the default is `1.1`.

Planned changes from different companies share atomic Sheets batches. `--batch-size 200` limits operations (including company status and Opportunity updates), so it is not necessarily 200 jobs. Uploads also split at a conservative local payload budget and the existing `2.2 MB` encoded API limit. Validation failures are isolated by company; ambiguous writes are never automatically retried. API request pacing and read retry/backoff remain unchanged.

`--sync-interval 60` uploads a partly filled batch after 60 seconds, checked between local company planning steps. A full batch uploads immediately, and remaining changes upload at the end. This interval is a flush trigger, not a guaranteed maximum visibility delay: a large company or slow Sheets call can take longer.

```bash
./job-search-scraper start --batch-size 200 --sync-interval 60
```

The dashboard separates **Processed locally** inventory items from **New jobs written**, which counts only newly inserted rows confirmed by Sheets. **Local queue** is the number of company inventories still saved in SQLite, and **Sync plans** is the number of frozen company write plans awaiting full acknowledgment. Local processing can finish well before synchronization. Reading Sheets, staging, validating/building requests, throttle waits, API writing, and saving checkpoints remain measured. API call counts include failed logical calls, but not internal client retries; payload sizes are uncompressed JSON bytes. Checkpoint payload bytes include durable inventories and frozen plans.

At completion or Ctrl+C, totals are saved beside the state database in `scraper-performance.json` (counts/timings only). View the last run with:

```bash
./job-search-scraper performance
```

### SQLite first, Sheets sync

Normal `start` now processes locally and automatically synchronizes consolidated batches. Defaults remain 5 fetch workers, assignment window 100, and batch size 200. The new partial-batch sync interval is 60 seconds; API request pacing remains 1.1 seconds. Local SQLite is the durable queue; Sheets remains the review interface, with fresh user edits checked before each upload.

To collect jobs first and run the Sheets synchronization in a separate invocation:

```bash
./job-search-scraper start --defer-sync
./job-search-scraper sync
```

`--defer-sync` reads the planning snapshot and updates startup/end cycle control records, while retaining full fetched inventories without job writes. `sync` never fetches job boards. Previously frozen plans replay exactly; inventories without plans use current screening rules. Each upload checks current company pauses, claims, board URLs and manual holds, and protects existing `Added to Opportunities?` decisions. Both commands use the same exclusive writer lock; run them sequentially.

After resolving a company write error, retry its retained payload with `./job-search-scraper sync --retry-blocked`. For failed fetches without usable inventory, use `./job-search-scraper start --retry-blocked`. `sync` also accepts `--batch-size`, `--sync-interval` and `--sheet-request-interval`. Without explicit retry, blocked inventories remain stored and skipped.

Keep the **whole `.state` directory**, including the inbox and any SQLite WAL files. Unsynced jobs now depend on that local storage. The inbox is restricted to the local account and bound to the spreadsheet ID; changing destinations requires retaining the original inbox with its original destination. Successful company syncs release their inventories and plans. Existing checkpoint databases migrate automatically, and legacy interrupted companies without saved inventory are refetched.

The writer loads the planning snapshot once per run and indexes Job History identities in memory. It updates that cache after confirmed writes. Subsequent Job History commits reread identity columns and the manual opportunity/review-lock cells, not full affected rows or the append tail. Small control tabs still use a single fresh read. Manual edits should be limited to `Added to Opportunities?` while the scraper is running; do not manually add/delete jobs, sort rows, or edit formulas during a writer commit.

New rows use grouped, explicitly addressed blocks inside the same atomic `batchUpdate`; updates use only contiguous changed cells. Explicit destinations allow validation before writing. The writer does not blindly retry a positional append after a timeout: restart resolves stable identities from Sheets, then replays the saved inventory. An ambiguous response or checkpoint interruption therefore cannot append the same keyed job again. Continue to avoid sorting/inserting/deleting sheet rows during a commit; the API does not offer a transaction spanning read and write.

See [the local processing benchmark](docs/local-pipeline-performance.md) and [earlier writer benchmarks](docs/writer-performance.md) for measured improvements and limits.

Blocked companies are not automatically retried. After you inspect the issue or change its configuration, explicitly request:

```bash
./job-search-helper resume --cycle CYCLE_ID --retry-blocked --apply --exclusive-writer
```

This does not bypass verification, logins, or access controls. It merely authorizes another normal retrieval attempt.

To repair blocked companies whose public careers page has moved to a different supported ATS board, preview the automated repair first:

```bash
./job-search-scraper repair-careers-urls --dry-run
```

The repair checks only companies marked `Blocked / Manual Review`. It skips writer/history conflicts, discovers a supported board from the configured careers page, then validates the candidate by fetching a complete inventory with at least one job. Apply the proven fixes only after stopping the scraper and other sheet writers:

```bash
./job-search-scraper repair-careers-urls --apply --exclusive-writer
```

A validated repair updates `Official Careers URL`, updates `ATS / Source`, clears the blocked fields, and changes `Scan State` to `Queued` so the next scraper pass can pick it up normally. If the command finds a candidate URL but cannot validate jobs, it leaves the company blocked and records the URL in `Candidate Careers URL` for manual review. The apply command creates that optional header when needed.

## Clean up previously recorded blacklist matches

The scraper applies `title-blacklist.txt` before adding newly scraped jobs to Job History. To reconcile older Job History rows after changing that file, run:

```bash
./job-search-scraper cleanup-blacklist
```

This is an apply command. Stop the scraper and other sheet writers first. To preview without changes:

```bash
./job-search-scraper cleanup-blacklist --dry-run
```

This command changes only `Added to Opportunities?` to `No`. It does not delete Job History rows or Opportunities, and it preserves all other fields. Rows already set to `No` are idempotent. Rows with `Review Status` set to `In Progress`, or rows without a unique stable identity, are reported and skipped. The blacklist is loaded fresh each time the command starts.

## Screen saved job titles without AI

Two editable files control title screening:

- `title-blacklist.txt`: excluded roles and seniority levels. All existing exclusions remain in effect. Staff, Principal, and Director are excluded even when the function otherwise matches.
- `title-review-list.txt`: preferred applications, product, customer-facing technical, field support, and field service roles. Matching this list is a review hint, not automatic acceptance or an allowlist. Jobs outside the shortlist still go to AI review unless an exclusion applies.

Exclusions always take priority. Unmatched titles remain uncertain. Phrases match whole words, ignore case, and allow punctuation between words; `regex:` entries support deliberate regular expressions. Restart a running scraper after editing either list.

To screen existing Job History rows and set excluded titles to `No`:

```bash
./job-search-scraper cleanup-titles
```

Stop the scraper and other sheet writers first. This applies immediately, just like `cleanup-blacklist`; no separate apply step is required. For an optional read-only report, use `./job-search-scraper cleanup-titles --dry-run`.

Both cleanup commands use the same rules and report excluded, potentially good, and uncertain title counts. The report lists potentially good and uncertain rows that are not already `No`. Only excluded titles can be changed, and only the `Added to Opportunities?` cell is updated. Existing `No` decisions are never promoted, active reviews and unresolved identities are skipped, and other fields and Opportunities rows are preserved. No model calls or AI tokens are used. Future scrapes use the same exclusions before inserting jobs.

## Scraper preferences and restarting

The existing blacklist is preserved, with `saas` and `software as a service` added. It still overrides the preferred list, including the existing literal `senior engineer` and `lead engineer` entries. Senior and Lead are not blanket exclusions; for example, Senior Product Manager and Lead Field Applications Engineer remain eligible when no other rule matches.

New jobs also receive conservative, local Python screening:

- Annual USD **base** salary must reach $120,000. A range ending at $120,000 qualifies for review. Bonus, commission, equity, and OTE do not count. Missing, hourly, foreign-currency, or unclear compensation stays eligible for AI review. Clearly labeled salary evidence in descriptions is checked too.
- Travel up to 50% is acceptable; explicit travel above 50% is excluded. Unknown or ambiguous travel stays for review.
- Only permanent jobs qualify. Explicit contract, temporary, fixed-term, contract-to-hire, internship, and seasonal employment is excluded; unspecified employment stays for review. Working with customer contracts is not contract employment.
- Prefer hardware and mixed hardware/software products. Explicit SaaS product responsibilities are excluded, but incidental SaaS tool use, integrations, or experience requirements do not exclude a job. Other uncertain product types stay for AI review.
- All locations, relocation, onsite, hybrid, and remote arrangements are eligible.

Preferred titles include Field Application(s) Engineer, Application(s) Engineer, Product/Customer Applications Engineer, Product Manager (including Assistant, Associate, and Technical), Product Owner, Product Line Manager, Solutions Engineer, Sales/Pre-Sales Engineer, Customer Engineer, Product Engineer, Product/Technical Product Specialist, Field Support, and Field Service. **Unmatched titles are retained for AI review**, with a note explaining that they fall outside the preferred shortlist. No missing preference is treated as an automatic rejection.

Blacklist matches are skipped before insertion and reported in the terminal. Other clear exclusions on new jobs are saved to Job History as `No` / `Reviewed` / `Reject`, with the evidence and Rejection Reason retained. Existing jobs keep the existing reassessment workflow: manual No decisions and review notes are preserved, and In Progress rows are untouched. This change does not retroactively sweep existing jobs. The title cleanup commands remain title-only; they do not apply travel, employment, or description rules.

You can leave an existing scrape running during a code update. To load the new rules, press Ctrl+C once, wait for the process to exit, then run `./job-search-scraper start` with your preferred worker/batch options. An interrupted upload replays its frozen keyed changes after restart; locally acknowledged batches are skipped. Saved inventories and plans resume from SQLite; legacy interruptions without saved inventories are refetched. Already saved jobs are not duplicated. Completed companies remain completed in the resumed cycle and receive the new rules on the next full scan. Keep `.state`; do not start a second writer. Fetch workers may take time to finish outstanding requests before the interrupted process exits.

## Assessment objective for the reviewing AI

Use these preferences as authoritative over wording in old resume samples:

- Apply the title exclusions first. Staff, Principal, and Director roles are outside scope, including otherwise relevant functions.
- Favor higher recall for credible **Strong**, **Possible**, and **Stretch** roles. Evaluate actual responsibilities, autonomy, customer influence, and leadership scope, not a management title alone.
- Prefer the applications, product, customer-facing technical, field support, and field service roles listed above, especially hardware and mixed products. Keep other nonblacklisted titles for full responsibility review; the shortlist is not an allowlist. Exclude explicitly SaaS-focused roles, explicit nonpermanent employment, and travel requirements above 50%. Unknowns stay for review.
- Reject mandatory security-clearance requirements, including obtaining and maintaining a clearance. Distinguish merely preferred clearance from a requirement.
- Reject jobs requiring this candidate to author software, firmware, scripts, algorithms, or test-automation frameworks. The candidate can operate tools, make minor or AI-assisted modifications, use APIs/webhooks, troubleshoot, and define objectives and logic for engineers. Primary systems-test/test-automation jobs are not targets. An occasional practical acceptance check in a field role is not automatically a coding job.
- Reject a stated **maximum annual USD base salary** below **$120,000**. Prefer compensation nearer **$180,000**. A range crossing the floor can qualify with a concern. Missing base salary remains `verify`, not evidence that the floor is met. Do not treat equity, bonus, OTE, hourly totals, or non-USD compensation as confirmed USD base salary.
- Any location, relocation, onsite, hybrid, or remote arrangement is eligible. Do not invent geographic exclusions or a pay premium. Surface travel, shift, rotation, and on-call concerns in the narrative.
- Use the approved Resume Samples and current, evidence-backed candidate profile for experience and resume selection. If that information is not available in the review session, ask for it rather than inventing skills or credentials. Resume selection follows role qualification, not employer industry alone.
- Keep one useful narrative explaining fit, supporting experience, gaps, salary/location concerns, recommended resume where supported, and meaningful changes. Preserve the user's personal notes and all application decisions.
- Never equate passing a title filter with passing a fit assessment. If hard-blocker evidence is unresolved, return `needs_info`; do not mark the blocker false without evidence.

## Decisions JSONL contract

Create a UTF-8 file containing **one complete JSON object per line**, without Markdown fences. Copy the exact `job_key` and `description_hash` from the exported pending record. The hash binds the decision to the description reviewed; stale decisions must not be applied to different content.

Illustrative single-line accepted decision:

```json
{"job_key":"COPY_FROM_EXPORT","description_hash":"COPY_FROM_EXPORT","decision":"accept","fit_level":"Possible","narrative":"Responsibilities match customer integration and troubleshooting. No required clearance, code authoring, or primary test automation was identified in the reviewed requirements. Salary is not listed: verify at least $120,000 annual base. Resume recommendation requires the approved reference catalogue.","reviewer":"Manual review","policy_version":"2026-09-17-v1","mandatory_clearance":false,"code_authoring_required":false,"primary_test_automation":false,"base_max_usd":null}
```

Do not copy that narrative as a finding about a real job; replace it with specific evidence. The boolean fields must reflect a substantive review, not merely absent parser matches.

| Field | Meaning |
|---|---|
| `decision` | `accept`, `reject`, or `needs_info`. Only accept may add an Opportunity. |
| `fit_level` | `Strong`, `Possible`, or `Stretch` for accept. |
| `narrative` | Evidence-based assessment/change explanation; not just a score. |
| `reviewer` | Person or manually operated review session accountable for the decision. |
| `policy_version` | `2026-09-17-v1` for this explicit policy. |
| `mandatory_clearance` | Boolean after review, or `null` if unresolved. |
| `code_authoring_required` | Boolean after review, or `null` if unresolved. |
| `primary_test_automation` | Boolean after review, or `null` if unresolved. |
| `base_max_usd` | Verified maximum annual USD base, or `null` when unknown/noncomparable. |
| `material_change` | Required when reassessing changed previously evaluated content. `true` means a completed substantive reassessment; `false` is a nonmaterial baseline refresh, not permission to silently change a prior decision. |

Accept requires the three hard-blocker flags to be explicitly false and must not contradict a below-floor salary. `needs_info` keeps the job pending and the company incomplete. A substantive reconsideration is counted only after its completed assessment is successfully committed. Initial assessment is count 0; counts 1 and 2 are the two allowed reconsiderations. At 2 the posting freezes for automatic monitoring. Do not call routine retrieval, a retry, or a whitespace-only change a completed reconsideration.

The current Opportunities dropdown uses legacy fit labels. The helper retains compatible labels and explains the precise Strong/Possible/Stretch conclusion in Notes rather than silently changing the workbook's validation rules.

## Recordkeeping and safety boundaries

- The operational tab allowlist is Companies, Job History, Opportunities, and Scan Cycles. The stored Prompt Library is not fetched or executed by normal processing.
- Existing application decisions, Date Applied, personal Notes, and formulas are not whole-sheet rewritten. A new accepted job starts as Not Reviewed with Date Applied blank.
- Source text is written as literal cell text, not as a spreadsheet formula. Per-job related writes use one Google Sheets batch request; there is no clear-and-rewrite operation.
- Posting IDs and identity-bearing URL parameters are preserved. A new posting ID is distinct even when the title matches; tracking changes alone do not create a new job.
- Description/hash baselines, pending reviews, and the local checkpoint permit resuming unfinished work. Keep the `.state` directory for efficient resumption and preserve the spreadsheet records. If local state is lost, `resume --cycle CYCLE_ID` can reconstruct that named cycle from the saved remote cycle/company/job records; it does not silently restart a completed cycle. Export reviews only after that recovery. Do not delete state to force a new run. Schema changes or an independent second helper require reconciliation, not a blind restart.
- The reconsideration cap applies to an exact posting. A frozen job's Last Checked must not move forward as though it was verified. A broad company API may still return its text incidentally; the helper does not reassess it or reactivate it.
- Only complete, valid, comparable inventory results may affect missing-scan counts. An unsuccessful request, unexpected empty/malformed response, partial page, hard-filter change, or blocked site is not closure evidence. Repeated absence is an inferred removal, not proof of an explicit official closure notice.
- The installed Apps Script is not required for this helper's runtime and is not edited by the installer. An existing Date Applied trigger is a separate manual-edit convenience; API writes do not trigger Apps Script `onEdit`.

## Deliberate first-version limits

**One writer only.** The local lock prevents another instance sharing this project's state directory from writing concurrently. It cannot atomically claim companies across machines, stop another agent, or prevent a human from sorting rows. `--exclusive-writer` is your confirmation that conflicting writers are stopped, not a remote lock. `--workers 2` is rejected. The existing Apps Script claim fields are not used as a claim of concurrency safety. A real multi-worker rollout needs atomic claims, expiry/token fencing, and result commits through the same coordinator.

**No autonomous AI assessment.** This implementation provides a queue and validates explicit imported decisions. There is no dormant Gemini extraction routine described as if it evaluates fit. Future model integration needs explicit configuration, privacy boundaries, cost limits, structured outputs, and its own tests.

**Three supported public ATS families, with careers-page discovery.** Other hiring systems remain manual work. Discovery finds explicit supported links on the configured page; it is not a universal crawler or browser renderer. The initial provider checks are evidence of current API compatibility, not a guarantee against future ATS changes.

**Conservative identity migration.** Existing legacy History keys are retained when the official URL matches. If the same posting ID moves to another URL, the helper keeps its existing Opportunity identity and appends the current official URL to Notes. If an employer reuses one URL for a genuinely different posting ID, the helper stops for manual disambiguation rather than merging the postings. A future hidden Opportunity Job Key column can remove that limitation, but this installer does not silently change your workbook schema.

**Conservative API pacing.** Google reads and writes are separated by at least 1.1 seconds per request. Fresh identity checks protect your data but make this first version slower; a completed small test is more important than full-list throughput. Use only one project copy as the live writer.

**No applications sent.** The helper never submits applications, contacts employers, changes your application decisions, or modifies the backup workbook.

**Offline tests are not a live-production certification.** Fixture tests and mocked Google requests can verify parsing and write construction. They cannot confirm your installed Python/venv packages, OAuth consent setup, network, live endpoint coverage, concurrent human activity, or actual Google write permission. The small, explicit live test is still required on your workstation.

## Review and documentation sources

See `REVIEW.md` for the section-by-section audit of the original script. Provider/schema behavior was checked against primary documentation:

- [Google Sheets batch requests](https://developers.google.com/workspace/sheets/api/guides/batchupdate)
- [Google Sheets Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python)
- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever public Postings API](https://github.com/lever/postings-api)
- [Ashby public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [Apps Script trigger restrictions](https://developers.google.com/apps-script/guides/triggers)

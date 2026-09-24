# Review of the Gemini-generated installer

## Bottom line

Do not run the pasted installer against the working workbook. As pasted, it contains execution-blocking Markdown corruption. Even after correcting that formatting, it does not implement the requested workflow and its spreadsheet writer can erase or overwrite workbook content. Appending an `EOF` marker and installing dependencies does not address those problems.

The replacement is `install_job_search_helper.sh`. It creates a fresh, uniquely named directory, a virtual environment, the complete source and tests, and a model-free review-first CLI. It does not automatically edit Google Sheets or start a search. Full operating instructions and the job-assessment objective are in `README.md`.

This is a source-level review, not a claim that the original program was run against Google Sheets. The review below follows the submitted files and their statements in order. Repeated imports and straightforward field declarations are grouped; every substantive operation and control path is covered. Some formatting damage may have occurred while copying the response, but a terminal executes the pasted characters, not their intended formatting.

## 1. Shell wrapper and project creation

| Submitted statement | Finding and required correction |
|---|---|
| `\#!/usr/bin/env bash` | An escaped `#` is not a valid shebang. Use `#!/usr/bin/env bash` in a saved script, or a quoted `bash` heredoc for a terminal-paste installer. |
| `set -euo pipefail` | Useful error handling, but not a transaction or a safety guarantee. It does not reverse an earlier deletion or failed remote write. |
| `PROJECT="job-search-helper"` | A relative directory name is reasonable if the installer reports where it is creating the project. |
| `rm -rf "$PROJECT"` | Critical: deletes an existing project, including credentials, local history, and user changes. Refuse an existing destination; never delete it automatically. |
| `mkdir -p` followed by `cd` | Should run only after checking prerequisites and confirming the destination does not exist. Fail cleanly on directory-creation errors. |
| Repeated quoted heredocs | The quoting is appropriate for preserving literal source text. Unfortunately, it also preserves the unwanted backslashes, Markdown fences, and malformed URLs in this submission. |
| `chmod 600 .env` | Good for an environment file, but token files and their parent directory need appropriate permissions too. |
| `touch .../**init**.py` | This is not `__init__.py`. Depending on glob matches, it creates or touches unintended names. Generate ordinary `__init__.py` files explicitly. |
| No interpreter check | Check Python 3.11+, `venv`, and `pip` before building. Give actionable errors rather than partially installing. |
| No venv/install/test commands | The requested one-paste setup is incomplete. It never creates `.venv`, installs the package, or runs tests. |

### Formatting that prevents execution

- Literal `\_` sequences inside quoted heredocs corrupt Python identifiers and some TOML strings. In unquoted shell paths, a backslash before `_` may simply be removed by the shell; this does not repair the same characters inside the file contents.
- Class and function bodies lack necessary indentation in several sections.
- Embedded triple-backtick fences are not Python syntax.
- Markdown links such as `[https://...](https://...)` are not valid Google OAuth scope strings or ordinary job URLs.
- `**name**` and `**main**` are not `__name__` and `__main__`.
- The README heredoc is not reliably terminated in the submitted command; explanatory prose and suggested repairs appear inside its intended body.

An unterminated Bash heredoc typically produces a warning and consumes the remaining input as heredoc content. It is not correct to promise that it always produces the exact `unexpected EOF while looking for matching EOF` error shown in the submitted explanation. On an interactive paste, Bash may instead continue waiting for the terminator. Appending a terminator blindly can swallow intended commands into the README and still leave the Python unusable.

## 2. `pyproject.toml`

| Section | Review |
|---|---|
| Build backend | `setuptools.build\_meta` is corrupted; the intended backend is `setuptools.build_meta`. |
| Project metadata and Python requirement | Reasonable once the installer actually enforces the Python minimum. |
| Dependencies | Reasonable building blocks, but the large set is unnecessary for the implemented functionality. Broad minimum-only versions are not reproducible and still require compatibility testing. |
| Gemini dependency | Installed even when unused. Prefer an optional dependency for an opt-in adapter. |
| Test dependencies | Their presence does not establish that tests are installed or run. `pytest-httpx` is unused by the supplied tests. |
| Console entry point | `job\_search\_helper.cli:app` is corrupted. The intended entry point is `job_search_helper.cli:app`. |
| `src` package discovery | Appropriate with valid package names and files. |

## 3. `.gitignore`, `.env.example`, and `.env`

- `**pycache**/` is not the normal `__pycache__/` pattern. Escaped wildcard and underscore patterns also need correction in the generated literal file.
- Ignore generated output, logs, caches, build artifacts, local databases and database sidecars, token files, and OAuth client files. Do not accidentally include credential files through later packaging.
- `SCRIPT_ID` is missing despite the earlier parallel-worker requirement. A safe first release can intentionally disable parallelism, but it must say so and reject `--workers > 1`.
- Environment variable names contain literal `\_` in the generated file and will not match valid Python environment lookups after only partial repairs.
- The `.env` file must not overwrite an existing configuration. The installer should use a new destination and initially contain no API key.
- There is no need for a Gemini key to use the default helper. The README instruction to put a “NEW Gemini API key” in `.env` misleadingly makes it sound required.

## 4. `config.py`

- The dotenv import and constant names are syntactically corrupted as pasted.
- Configuration is evaluated at import time, which makes test isolation and project-directory selection harder. Load a typed settings object from an explicit project path.
- Empty values are not comprehensively validated. Paths, spreadsheet ID, authentication mode, and worker count should fail early with clear messages.
- No default read-only scope policy, secret-redaction policy, project-relative path handling, or configured-worker safety guard is implemented.

## 5. `models.py`

- The dataclass fields are sensible starting fields, but indentation and identifiers are invalid as pasted.
- No validation prevents missing posting IDs, URLs, or titles from reaching the pipeline.
- An inventory must carry more than a list of postings: source, completeness, error/blocked reason, fetched-at time, and a stable inventory/run identifier are necessary for safe closure handling.
- Keep public posting ID separate from internal requisition ID. They are not always one-to-one.
- The model lacks explicit pending-review state, saved source snapshots, prior assessment, and decision provenance needed by the workflow.

## 6. `canonicalize.py`

| Operation | Review |
|---|---|
| Tracking-parameter set | `gh_jid` can identify the job on an embedded Greenhouse careers page. Removing it can collapse different jobs into one URL. Preserve identity-bearing parameters; remove only known marketing parameters. |
| Parse query | Reasonable once syntax is fixed. Sort remaining query pairs for stable identity where order is not meaningful. |
| Lowercase scheme/host | Appropriate; do not lowercase the path or job identifier without evidence that they are case-insensitive. |
| Strip trailing slash | Usually helpful for these sources but should be tested against intended ATS URLs. |
| Drop fragment | Appropriate for tracking-only fragments; explicitly support any source that uses meaningful fragment routing. |
| Company plus requisition ID | Can collide across sources or distinct published posts sharing an internal requisition. Prefer stable company ID plus ATS/source plus public posting ID. Preserve a separate requisition field. |
| URL fallback | Fail on a missing or invalid canonical URL instead of producing a shared empty key. |

## 7. `filters.py`

- The unconditional “keeper” return precedes every exclusion. Thus a title like `Payroll Operations Manager` or `Software Engineer, Developer Support` can bypass a genuine exclusion solely because it contains `Operations` or `Support`.
- Conversely, standalone `mobile`, `medical`, `clinical`, `controller`, and `audit` are too broad. `Mobile Field Service Engineer`, `Medical Device Field Applications Engineer`, or a technical controls-related title can be relevant.
- `Field` is absent from the keeper patterns even though it was explicitly requested for contextual review. Adding another blanket exemption would not fix the ordering problem.
- `Test Engineer` should receive context review, not automatic acceptance. The user's preference against primary test-engineering/code-writing work must still be applied during fit review.
- The implementation is hard-coded, not a small configurable rule set with a rule version and recorded rejection reason.
- The helper should keep a narrow, conservative title filter. It must not infer overall fit from surviving that filter.

## 8. `material_changes.py`

- HTML-to-text conversion, whitespace normalization, and SHA-256 hashing are useful deterministic operations.
- Only description text is normalized; title/location/arrangement/compensation still change hashes for insignificant formatting differences.
- Joining arbitrary fields with `|` is ambiguous when their contents contain that separator. Serialize a fixed keyed structure deterministically instead.
- Hash inequality proves text changed, not that the change is substantive. Boilerplate changes should not automatically consume a reconsideration.
- `has_material_change` returns false when an existing record lacks a prior hash. Such legacy records need an initial baseline/review path, not silent reuse.
- There is no old/new snapshot or field-level change summary. A hash cannot explain what changed.

## 9. `ats/base.py`

- HTTP timeout, user-agent, explicit client close, and exception types are good foundations.
- `follow_redirects=True` needs a controlled destination policy if arbitrary URLs can ever enter the request path. The adapters should accept only validated supported public ATS endpoints.
- Treating every 429 as permanently blocked loses the opportunity to honor a bounded `Retry-After`. Retry transient throttling within a strict budget; do not retry human-verification/access-denied responses repeatedly.
- Other status failures are called `PartialError` even when no partial inventory exists. Distinguish blocked, temporary failure, malformed response, partial coverage, and unsupported source.
- Error strings can expose request URLs or sensitive parameters in more general HTTP workflows. Emit sanitized summaries.
- There is no rate limiter, JSON schema validation, completeness result, or per-page retry logic.

## 10. `ats/greenhouse.py`

- The public board endpoint and request for description content are the right general approach.
- The retry decorator retries all exceptions from the method, including permanent access errors and parsing bugs. Retry only transient transport/server/throttling failures.
- `data.get("jobs", [])` treats a malformed or unexpected response as a valid empty board. That can later close jobs incorrectly. Validate the response shape and completeness metadata.
- Preferring `internal_job_id` over posting `id` can merge distinct public postings. Use the stable public posting ID for inventory identity and preserve the internal ID separately.
- Department, location details, compensation metadata, and supported completeness information are discarded.
- There is no explicit rate limiting or complete/partial indicator.

## 11. `ats/lever.py`

- The public postings endpoint is appropriate for a validated board. European Lever boards need the appropriate regional host.
- The code makes one request and does not implement the documented `skip`/`limit` pagination. It cannot safely assert complete inventory coverage.
- `descriptionPlain` or `description` alone omits structured `lists` and `additional`/`additionalPlain` sections. These often contain responsibilities and required qualifications—the most important fit evidence.
- Structured compensation is discarded; the normalized compensation field is always empty.
- Public posting ID and hosted URL are useful identity fields.
- The response must be validated as a list of valid postings. A malformed entry must prevent a “complete” assertion.
- Retries, rate limiting, and completeness have the same issues as the base adapter.

## 12. `ats/ashby.py`

- The public job-board endpoint is the right general source for a validated board name.
- Compensation retrieval is not requested with `includeCompensation=true`, and compensation is discarded even if returned.
- The code ignores plain-text descriptions, workplace/remote fields, secondary locations, and other useful structured data.
- A missing `jobs` property becomes a successful empty list, which is unsafe.
- Source timestamps must reflect fields actually provided by the endpoint; an assumed `updatedAt` field should not be treated as a guaranteed source update timestamp.
- Unlisted postings should be handled according to the published feed's visibility flags and the user's official-public-only policy.
- As with the other adapters, an inventory result must explicitly state whether coverage is complete.

## 13. `ats/__init__.py` factory

- Case-insensitive selection among three known adapters is reasonable after the filename and identifiers are fixed.
- Returning `None` for an unsupported source is acceptable only if the pipeline records `Manual Review` with the official URL and disables automatic retry as configured. Merely printing and skipping loses the work item.
- Constructor injection for HTTP transport, rate limiter, retry budget, and fixtures would make offline testing much easier.

## 14. `google/auth.py`

- The supplied scope is a Markdown link rather than a valid OAuth scope URL.
- The code always asks for full Sheets write access, including a preflight or dry-run. Separate read-only authentication from explicit write authorization.
- Preflight can unexpectedly open a browser. Make login an explicit command; preflight should report missing auth without initiating consent or remote writes.
- Refresh handling is a useful starting point, but an expired/revoked token needs a sanitized, actionable error.
- Token output permissions are not constrained. Use a private directory and atomically write the token with restrictive permissions.
- Verify that an existing token actually grants the requested scopes; do not silently assume it does.
- Tokens must not be printed, included in exception text, included in reports, or bundled in deliverables.

## 15. `google/repository.py` — highest data-loss risk

| Operation | Finding |
|---|---|
| `read(tab)` | Reads entire tabs and assumes the first row is a unique, exact-case header map. Normalize aliases, detect duplicate headers/keys, and quote sheet names correctly in A1 ranges. |
| Missing trailing cell handling | Filling absent values with empty strings is reasonable for a read model, but does not justify writing them back over formulas or newly added user data. |
| `replace(..., dry_run)` | A caller-controlled boolean is a weak safety boundary. Enforce write authorization in the repository/commit interface itself. |
| Header discovery from data rows | Empty tabs with existing headers are mishandled. Headers must be read and validated independently of whether data rows exist. |
| Whole-tab `values.clear` | Critical: erases all values and formulas in the tab before the replacement is written. If the next request fails, the sheet stays blank. |
| Whole-tab update from old snapshot | Critical: overwrites edits the user made during scanning, including application status, dates, and personal notes. Reading the workbook once does not preserve concurrent edits. |
| `USER_ENTERED` | Public job text beginning with `=` can be interpreted as a spreadsheet formula. Use `RAW` for untrusted scraped text. This also avoids unintended date/number conversion. |
| Unknown keys dropped | New dictionaries use `Title`, `URL`, `Fit Review`, and `Status` without checking the real workbook headers. When they differ, those values disappear from the write. |
| No idempotent transaction boundary | History and Opportunities are written separately; a partial success leaves them inconsistent. Use narrowly scoped, idempotent updates with an explicit commit marker/checkpoint and repair on resume. |

Never rewrite complete data rows containing user-owned columns. Write only managed cells/columns after validating the live header map and unique job key. Recheck ownership and existing records at commit time. A local single-writer lock can prevent two local processes from colliding, but it cannot make independent Google writers atomic; parallel remote commits must remain disabled until a real coordinator protects the entire commit.

### Confirmed mismatch with the current working workbook

The live working-copy headers were inspected read-only during this review. These are concrete mismatches, not hypothetical naming preferences:

| Original code writes/expects | Actual workbook | Effect of the original writer |
|---|---|---|
| Opportunities `Title` | `Job Title` | New job title is discarded. |
| Opportunities `URL` | `Job URL` | New official URL is discarded. |
| Opportunities `Job Key` | No Job Key column in current A:L schema | The new key is discarded; deduplication cannot rely on that field without an explicit migration. |
| History `Title` | `Job Title` | New history title is discarded. |
| History `URL` | `Official Job URL` | New history URL is discarded. |
| History `Status` | `Job Status` | Active/Closed changes are discarded. |
| History `Company ID` | No Company ID column in current A:X schema | Company-history matching by this field fails for existing rows; the closure loop has no corresponding records. |
| History `Requisition ID`, initial dates, review outcome | Existing columns, not populated by the original pipeline | Relevant fields are left blank despite their presence in the schema. |

Current Opportunities headers are `Company`, `Job Title`, `Job URL`, `Location`, `Salary / Range`, `Work Arrangement`, `Fit Review`, `Application Status`, `Date Applied`, `Date Found`, `Last Checked`, and `Notes`. Column L is Notes, not New?.

Existing Job URL cells may contain rich-text hyperlinks with a display label rather than a literal URL. A values-only read is not sufficient to recover every existing official link; read the cell hyperlink/rich-text metadata or fail safely if identity cannot be resolved. Never conclude that a displayed job title is the URL.

Current Fit Review validation uses `Strong Potential Fit`, `Potential Fit`, `Unlikely Fit`, and `Not Relevant`. Translate the semantic Strong/Possible/Stretch result explicitly; for example, preserve `Potential Fit` as the cell value and explain `Stretch` in the designated review narrative. Do not silently add unrecognized dropdown values. Current Job History status validation uses `Open and verified`, `Closed`, `Unable to verify`, and `Not verified`, so `Active` is not a valid substitute.

## 16. `checkpoint.py`

- SQLite is a suitable local cache/checkpoint tool. Context-managed transactions and parameterized SQL are good choices.
- Only cycle/company completion exists; there is no durable job-level progress, pending decision, saved inventory, or remote commit receipt.
- `mark_complete` is called before any remote write. A crash or failed write therefore leaves a company locally “completed” even though none of its results were saved.
- A dry-run also writes completion state into the same database used for real runs. Preview work must not mark applied work complete.
- Cycles never transition to completed, and the class has no active-cycle lookup or resumable work queue.
- A local cache alone does not satisfy the earlier requirement that the workbook expose scan progress and recovery state.
- Tests must simulate failure between each persistence step, not just a clean successful run.

## 17. `gemini.py`

- The function name `evaluate_fit` is misleading: it extracts generic skills, management, and a summary. It has no candidate profile and cannot determine personalized fit.
- The pipeline never imports or calls this function, and the CLI never exposes `--use-gemini`.
- A configured API key alone enables a call if this function is invoked. Require an explicit command-line opt-in as well.
- A hard-coded model can become unavailable; make the model explicit/configurable and fail closed without silently choosing another paid model.
- JSON is requested in prose but never schema-validated. Treat output as untrusted structured extraction, not an instruction or automatic decision.
- No explicit timeout/retry budget, usage summary, or redaction guard is implemented.
- The default helper needs no model calls. Optional public-description extraction must never send résumés, private notes, sheet contents, or credentials.

## 18. `pipeline.py`, initialization and workbook reads

- Dependencies injected into `Pipeline` help testing, but the flags do not create a robust write boundary.
- `checkpoint.start` changes persistent local state even for dry-run.
- Entire Companies, Job History, and Opportunities tabs are read without schema validation, duplicate-key checks, or managed/user-owned field separation.
- Existing records are indexed only from Job History. A job already present in Opportunities but absent from History can be appended again.
- `history_index` is built once and never updated for newly appended rows. Repeated keys within an inventory can append duplicate history entries.
- Duplicate preexisting Job Keys are silently collapsed in dictionaries instead of reported for repair.

## 19. `pipeline.py`, company selection and retrieval

- Blank Company ID rows are skipped forever; this fails the “new company with blank Date Added” requirement when IDs also need initialization.
- Company Status, Scan State, Automatic Retry, blocked status, current cycle, and claims are ignored.
- `extract_board_id` takes the final path segment, so an employer `/careers` page becomes board `careers`, a job detail URL becomes a job ID, and some trailing-slash/query combinations are parsed incorrectly. Parse only supported official ATS board URLs and keep an explicit validated board/source mapping.
- Unsupported ATS sources are printed and forgotten rather than added to the manual-review queue.
- A caught exception causes silent continuation; company scan state, reason, incomplete coverage, and retry policy are not persisted.
- The client closes in `finally`, which is good.
- Any returned list is treated as a complete inventory. The pipeline cannot distinguish targeted results, malformed empty responses, partial pagination, or successful complete retrieval.

## 20. `pipeline.py`, per-job processing

- Title exclusion happens before adding the posting to `inventory_keys`. A previously tracked job whose title now triggers a filter is falsely treated as absent. Inventory presence must be collected before any fit/title filter.
- A hash is generated, but no source snapshot or readable change summary is retained.
- Frozen jobs are skipped when present, but not protected later in the absence/closure loop.
- `Last Evaluated` is refreshed whenever a known job appears, even if no review took place. Verification time and completed evaluation time are different facts.
- On change, the count increments before any substantive review. An interrupted or never-reviewed change consumes the limited reconsideration budget.
- The new hash overwrites the last evaluated hash before a review. The next run sees “unchanged” data even though the previous change has not been evaluated.
- `Reconsideration Status` becomes `Needs Reconsideration`, but it never becomes the required frozen state after a completed second review.
- `Status = Active` can reopen records without a policy or corresponding opportunity status update.
- Unknown rows are appended directly to Opportunities with `Fit Review` blank. Passing a title filter is not evidence of Strong, Possible, or Stretch fit. This incorrectly adds mandatory-clearance jobs, code-authoring roles, under-floor salary jobs, and unrelated positions.
- New opportunities do not reliably set `Application Status = Not Reviewed`, `Date Found`, correct official link, narrative, location, or any other required workbook fields.
- The pipeline contains no explicit human/AI review queue or decision-import operation. That handoff is essential to keep the default helper model-free while still applying real fit decisions.
- There is no immediate per-job persistence or post-write “Added” notice.

## 21. `pipeline.py`, closure and final writes

- Two absences are counted without proving that either inventory is complete.
- The absence counter has no distinct inventory/run ID guard; repeating a checkpoint step can count the same inventory twice.
- Filtering before the presence set creates false absences.
- Frozen postings can continue accumulating absence counts and be closed despite the requested stop-checking rule.
- Explicit official closure is not implemented.
- Closure updates only History, not the corresponding scanner-owned job status in Opportunities.
- Company completion is checkpointed before the end-of-run bulk writes. A failure anywhere in those writes can lose an entire cycle while leaving misleading local completion markers.
- Unsupported or failed companies do not prevent the CLI from printing “finished successfully.” Report completed, blocked, failed, partial, and pending-review counts distinctly.

## 22. `cli.py`

- The Typer application and explicit dry-run/apply switch are useful starting choices after syntax repair.
- Every `run` creates a new random cycle. There is no way to resume the same cycle, so the checkpoint skip logic does not solve interruption recovery.
- Requested `inventory --company-id`, `cycle start`, `cycle resume`, `cycle status`, `test-fixtures`, `--workers`, `--verbose`, and `--use-gemini` interfaces are absent or different.
- `cycle_status` only prints a filename; it does not report actual progress or status.
- `test` assumes pytest is installed even though it is only an optional dependency and the installer never installs it.
- The broad exception printer can reveal raw exception details and calls failed/partial runs successful when errors were caught further down.
- Preflight validates only spreadsheet access. It must validate the required tabs, live headers/aliases, unique IDs, supported ATS configuration, credentials/scopes, and that the target is the intended working copy.
- `if **name** == "**main**":` is corrupted Python.

## 23. `tests/test_core.py`

The submission contains seven small tests, all for pure helpers. As pasted, several tests are syntactically corrupted or use Markdown-wrapped URLs. Even once repaired, they do not test the dangerous code paths.

Missing coverage includes every ATS adapter, pagination, blocked/partial/malformed responses, rate-limited retries, schema mismatch, read-only enforcement, formula injection, preserving concurrent user edits, resume after failure, remote write failure, existing opportunities without history, duplicate inputs, reconsideration completion versus detection, frozen closure behavior, idempotent missing counters, new company initialization, and unsupported/parallel worker rejection.

Passing the seven supplied tests would not establish that the job-search workflow works safely.

## 24. README and appended repair advice

- The README does not document schema mappings, authority boundaries, safe preview/apply workflow, review queue/decision import, cycle recovery, data ownership, or a validation checklist.
- The appended prose is not executable shell code and is entangled with the unterminated README heredoc.
- The suggested `echo "EOF" >> script.sh && bash script.sh ...` command still runs the destructive directory deletion and unsafe spreadsheet writer. Do not use it.
- Hardcoded expected tab names are not inherently a bug: a clear workbook contract is appropriate. The real issue is missing schema validation and mismatched column names, not the existence of named required tabs.

## 25. Related issue: previously authored Apps Script

The current local `Job_Search_Master.gs` was inspected read-only. No Apps Script or Google Sheet was changed as part of this review. The earlier claim that this code is fully ready for parallel workers is not supported by the source.

| Function/path | Finding |
|---|---|
| `onEdit`: `getValues()` followed by `dateRange.setValues(dates)` | When one date is filled, the entire edited date span is rewritten. Existing formulas become their calculated values, and a formula returning an empty string can be replaced with a date. Check `getFormulas()` and update only truly empty individual date cells; preserve other cells and their formats. |
| `claimNextCompany` eligibility | `In Progress` is excluded before expiration recovery. A crashed worker's expired claim cannot be reclaimed in the ordinary state left by the code. |
| Blocked retry check | The `blocked / manual review` branch is unreachable because that state is excluded by the preceding eligibility test. Retry/requeue policy needs explicit handling. |
| `withClaimedCompany_` | Only the token is checked. Expiration, worker ID, cycle ID, and expected state are not validated. An expired token can still heartbeat or complete until replaced. |
| Job-result writes | No function validates a current claim and writes job history/opportunity results under the same lock. Atomic company assignment alone does not prevent a stale worker from writing results through Sheets API. |
| `SpreadsheetApp.getActive()` in API-facing functions | API execution must not assume an editor-bound active spreadsheet context. Use an explicitly configured, validated spreadsheet ID for headless execution. |
| Header maps | Duplicate normalized headers silently overwrite prior entries. Reject ambiguous schema rather than choosing a column silently. |
| Completion | The callback can assert `Complete` without proving complete retrieval/review coverage. It also updates Last Checked on incomplete outcomes. Company attempt time and successful verification need explicit semantics. |
| API readiness | Having functions in a bound script is not equivalent to a configured, authorized Apps Script API executable. Deployment, scopes, project configuration, and a live integration test are separate requirements. |

Until the full claim-and-commit path is corrected and tested, enforce a single writer and refuse parallel workers. A local lock protects only processes sharing that lock; it is not a global guarantee against another machine, script, or AI session writing independently.

## Acceptance criteria for the replacement

1. A fresh-directory installer passes Bash syntax validation, creates a venv, installs successfully, runs offline tests, and never deletes an existing project.
2. Default commands make no model calls and no Google Sheet writes. An explicit apply operation is required for each remote mutation.
3. The program validates the live working-copy schema and uses narrow literal-value writes only to its owned columns (`updateCells` with explicit `stringValue`/`numberValue`, equivalent to the safety intent of `RAW`). It never clears entire tabs or rewrites user application decisions, dates, notes, or formulas.
4. ATS inventories have validated public posting identity and explicit coverage. Lever pagination and full description sections are handled; compensation and arrangement are retained when available.
5. Surviving postings enter a review queue, not Opportunities. An explicit completed Strong/Possible/Stretch decision supplies the substantive review before adding a job as Not Reviewed. Rejected reviewed jobs remain in History.
6. Saved snapshots, review state, hashes, cycle IDs, and job-level checkpoints allow idempotent recovery after interruptions and partial writes.
7. Reconsideration counts only completed substantive reassessments. Detection, retries, and replays do not increment it. The second completed reconsideration freezes automatic checking as requested.
8. Closure counters advance once per distinct successful complete inventory, never for blocked/partial/failed scans, and do not update frozen jobs.
9. Unsupported or blocked sources become explicit manual-review items. A completed cycle stops; a later resume does not silently create another cycle.
10. Multiple writers/workers remain disabled until a verified coordinator protects claims and the entire job-result commit—not just assignment.
11. Offline tests exercise failure recovery and preservation, not merely normalization helpers. Report separately which checks were performed offline and which Google/ATS integrations still need live verification.

## Replacement validation — September 17, 2026

The complete replacement suite contains **141 passing offline tests**: 27 ATS/transport tests, 37 core/CLI tests, 35 engine/recovery tests, and 42 repository/OAuth tests. They use fixtures and mocked Google responses, not production writes.

The generated installer passed `bash -n` and was executed in a fresh temporary directory. It created its own Python virtual environment and passed the same 141 tests using that environment. Its CLI help and offline demo were also checked. The installer uses a unique destination and does not execute the original `rm -rf` operation.

The engine regression tests include interruption after a successful remote commit but before the local checkpoint, interruption midway through staging two jobs, loss of local state at the start of a new cycle, exact two-reconsideration freezing, changed posting URLs, ambiguous reused URLs, preservation of user application fields, and no closure from partial/blocked/incomparable inventories.

Not tested here: your workstation, real OAuth consent, dependency downloads for the optional Google extra, live ATS response completeness, or actual Google write execution/permissions. These require the documented small live test after setup. No live workbook or Apps Script was changed during this review. Parallel workers and automatic model API calls are intentionally disabled, not claimed as implemented.

### Primary API references

- [Google Sheets atomic batch requests](https://developers.google.com/workspace/sheets/api/guides/batchupdate)
- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [Apps Script API execution requirements](https://developers.google.com/apps-script/api/how-tos/execute)
- [Bound-script context restrictions](https://developers.google.com/apps-script/guides/bound)

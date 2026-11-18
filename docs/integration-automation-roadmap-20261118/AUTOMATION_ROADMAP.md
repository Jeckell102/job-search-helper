# Automatic company scraping and integration repair — development roadmap

Prepared 2026-11-18. This is a development plan, not activation of unattended work.

## Intended outcome

Adding an active company creates a durable request to scrape only that company. The normal scraper first tries the integrations it already has. When evidence shows that an integration is missing or broken, Python creates a repair task. The Jetson assists with the repair; MuleLab builds and tests it, validates real public jobs, installs the approved version, and runs that company's scraper again. Jobs are saved through the normal Job Search Helper storage and synchronization path.

Failures during existing scrape runs enter the same repair workflow. Other companies continue wherever the existing writer and scraper locks permit. A blocked company cannot prevent the repair queue from progressing indefinitely.

Success means the company's applicable jobs were durably saved using the working integration. Creating a file, passing fixture tests, or installing code is an intermediate state. Database completion and any pending Google Sheets synchronization must be reported separately.

## Verified starting point

| Building block | What exists | Remaining gap |
| --- | --- | --- |
| Company-scoped scraping | `Engine.start_cycle(company_ids=...)` and CLI selection exist. | The normal `job-search-scraper start` starts an all-company scan. A supported durable company-only entry point must use the full normal storage path. |
| Existing run coordination | Scraper/writer locks, cycle recovery and saved inventories exist. | `start_cycle` rejects an unfinished cycle; new-company requests must queue safely rather than supersede a running scan. |
| New-company intake | Startup discovers companies and assigns missing IDs. | The runner explicitly says no Sheets watcher remains after exit. Continuous database/intake detection is not established by startup discovery. |
| Python coordinator | Durable tasks, receipts, budgets, checkpoints, inference reservations, isolated workspaces and campaign accounting exist. | Successful Samtec recipe generation and the complete validation/install/retry sequence are not connected into an unattended pipeline. |
| Existing repair backlog | Backlog import and company identity reconciliation exist. | Reconcile entries against current company/source/integration versions before scheduling; historical counts and failures are not current truth. |
| AI-assisted integration | Samtec passed two fresh 148-job live inventories and independent QA; 60 installed tests passed. | This was a supervised, company-specific recipe. General recipe selection, evidence collection and automatic task progression remain to be proven. |
| Live validation and installation | Reviewed pilot scripts provide live reconciliation, exact source hashes, guarded installation, backups and rollback. | The coordinator still treats these as operator gates. They need explicit Python-controlled states and enforceable policies. |
| Final data delivery | The normal scraper has inventory and storage/sync machinery. | The pilot proved fetching and installed code, not a new normal company scrape committed through the complete storage/sync path. |

Correction to the earlier summary: a persistent Python coordinator and queue already exist. We should extend them, not build a second scheduler. What is missing is the reliable connection from company events through repair, release and confirmed data delivery.

## Ownership and resource limits

- MuleLab owns the database watcher/intake, queue, task state, public-page retrieval and rendering, development workspaces, tests, validation, releases, scrape retries, storage and GitHub backups.
- Jetson provides one shared inference lane. The model receives a bounded evidence packet for one company and phase at a time. Python retains the roadmap and decides the next state.
- Each integration receives fresh model context and an isolated workspace. Its durable history, budgets, evidence and retry relationships remain on MuleLab. Resuming does not erase expenditure or reopen an exhausted budget silently.
- Model output is a proposal. Public website text is evidence, not instructions. The model cannot change the acceptance criteria, grant itself permissions, mark itself successful or directly install code.
- No wrapper development files or job inventories are stored on Jetson. Existing runtime/model files remain there.

## Workflow and state model

```text
Company added or eligible source changed
                  |
           company-only request
                  |
             normal scrape <----------------------------+
                  |                                     |
          classify the result                           |
          /        |         \                          |
     success   temporary    integration repair needed    |
        |       retry               |                   |
   save jobs                 durable repair task         |
        |                           |                   |
   sync status              evidence + isolated build    |
                                    |                   |
                            offline + live validation    |
                                    |                   |
                          guarded release + fresh worker-+
```

External access blocks and ambiguous employer identity enter a visible blocked state with a next action. They do not loop through code generation.

Keep scrape requests, repair attempts, integration releases and publication receipts distinct but linked by company ID and source revision. Suggested repair states are `QUEUED`, `EVIDENCE_READY`, `BUILDING`, `OFFLINE_VERIFIED`, `LIVE_VERIFIED`, `RELEASED`, `RETRY_SCHEDULED`, and `COMPLETE`, plus retry-wait, blocked, failed and user-paused outcomes. Map existing coordinator states explicitly during migration; do not reinterpret old terminal receipts.

## Milestone 1 — Prove the company-only storage path

Provide one supported company-only command/API that calls the normal scraper and storage pipeline. Reuse existing identity validation, filters, full-description storage, duplicate handling and writer coordination. Reject empty or unknown company selections; never allow an omitted ID to become an all-company scan.

Run Samtec through this path. Confirm the public inventory is complete, normal filters are applied, applicable jobs and full evidence are durably saved, and rerunning does not duplicate records. Do not require all 148 public postings to become Opportunities: personal filters and manual decisions remain in force.

When a main scrape is already running, persist the request and schedule it at a safe boundary. Initially serialize company-only runs with existing scraper locks; do not create a parallel writer or supersede the user's current scan.

**Exit gate:** one company requested, only that company fetched, expected stored records verified, repeated execution safe, and local-save versus Sheets-sync status explicit.

## Milestone 2 — Detect new companies reliably

Connect company creation/update to a durable request outbox. For direct database writes, create the company event transactionally with the change where possible. For Sheets imports or external edits that bypass application code, add periodic reconciliation through the supported synchronization path.

Record a stable company ID and a revision of integration-relevant fields. Trigger on first eligible addition and meaningful careers-source changes, not status timestamps or the coordinator's own progress writes. Incomplete entries wait for required identity/source fields; paused or removed companies remain excluded.

Seed an initial watermark so enabling the watcher does not mistakenly treat the entire existing database as newly added. The historical backlog is imported separately and deliberately. At-least-once event delivery is acceptable when queue insertion and downstream writes are idempotent.

**Exit gate:** adding a company while idle and during a running scrape creates one logical scoped request; duplicate delivery, restarts and repeated synchronization do not create duplicate work or miss additions.

## Milestone 3 — Turn scrape failures into useful repair tasks

Emit a structured outcome from both full runs and company-only runs. Use deterministic classification first; AI can assist ambiguous diagnosis without overriding evidence.

| Outcome | Automatic action |
| --- | --- |
| Complete inventory, including verified zero openings | Save the result; no repair task. |
| Timeout, rate limit or temporary provider error | Bounded retry with backoff; preserve partial evidence. |
| Authentication problem, CAPTCHA/access block or uncertain employer | Hold with a clear reason; retry only under the defined policy or after relevant evidence changes. |
| Unsupported source or proven parser/description/pagination regression | Create or update one integration repair task. |
| Jobs fetched but database/synchronization fails | Retry storage/publication; do not rewrite the integration. |
| Company paused, removed or source changed during work | Cancel or supersede the stale request before installation or writes. |

Attach company/source identity, adapter version, error category, failure fingerprint, captured public evidence, expected behavior and the exact reproduction path. Deduplicate against existing active repair tasks and backlog entries. Link repeated incidents without resetting budgets. Partial inventories must not mark unseen jobs closed or advance a complete-check timestamp.

**Exit gate:** realistic failures produce the correct action; a failing company does not cause repeated repair creation, and a transient outage does not provoke an unnecessary code change.

## Milestone 4 — Automate bounded integration development

Integrate the successful pilot approach into the existing coordinator. Python gathers evidence, chooses the next phase, invokes one Jetson request, validates the response and records progress. The next company starts with fresh context assembled from durable facts.

Use a progression of repair capabilities:

1. Reuse a proven adapter or correct an evidence-verified source mapping.
2. Select a reviewed provider recipe with strict configuration validation.
3. Make a bounded code proposal in an isolated workspace when supported by that repair policy.
4. Hold unfamiliar website structures or repeatedly failing proposals for engineering review.

The Samtec recipe currently contains company-specific checks. Do not generalize it by removing identity guards. Build provider recipes with explicit, tested company/source bindings. A shared-provider change must identify and regression-test affected employers.

Generate fixtures from independently captured actual pages, including failure and empty-state cases. Preserve baseline tests. The AI cannot weaken tests or substitute a self-authored assertion of success for public evidence.

**Exit gate:** the coordinator can move a repair from failure evidence to a tested candidate without manual prompt copying; repeated no-progress reads stop with a checkpoint; an unsupported case is reported honestly.

## Milestone 5 — Automate validation, release and the company retry

Promote the pilot's reviewed scripts into maintained Python services with versioned receipts and regression coverage. A release requires all of the following:

- Relevant offline and routing tests pass, including affected shared-adapter regressions.
- Normal-dispatch live validation confirms employer scope, every results page, unique stable job IDs/URLs and full descriptions against independent public evidence.
- Empty listings have explicit employer-scoped zero-opening evidence. A naturally changing inventory gets bounded reconciliation rather than an endless identical-count requirement.
- The source version validated is the version released. If production changes in the meantime, rebase the bounded patch and revalidate instead of overwriting newer files.
- The installer holds a release lock, preserves unrelated source, creates a rollback artifact and records the new integration version. Tests and documentation accompany the integration.
- Existing scraping processes are not hot-patched. A fresh worker loads the release at a safe boundary and proves which version it used.
- Python creates a durable retry request for the original company and watches the ordinary storage result. A crash after install but before retry is recoverable without reinstalling blindly.

Keep release, backup, company scrape and publication statuses distinct. Record and retry GitHub delivery failures without falsely reporting a backup or repeatedly scraping jobs. If the installed integration fails a post-release check, roll back only the affected release when safe and reopen a bounded repair attempt; preserve existing job data.

**Exit gate:** an induced integration failure leads to a validated release, a fresh company-only scrape and verified saved jobs, without manual movement between the stages.

## Milestone 6 — Reliability, sequential operation and staged activation

Use queue leases and crash reconciliation to guarantee one current repair owner and one Jetson inference request. Adopt explicit per-attempt time/token/tool limits, a bounded number of automatic successor attempts, cooldowns and a persistent failure history. Exhaustion becomes a visible exception; it does not stop every later company or trigger unlimited retries.

Prioritize newly added companies and regressions of working integrations, then work through the reconciled historical backlog without starving it. Shared-provider failures can share investigation, but each affected company's recovery still needs its own scoped scrape receipt.

Expose plain-language statuses: waiting to scrape, retrying a temporary error, building integration, validating, installed/retrying company, jobs saved, synchronization pending, or blocked with reason. Provide pause/resume and separate controls for intake, scraping, repair generation and automatic releases.

Activation sequence:

1. Observe-only intake and classification: show proposed tasks without running them.
2. Automatically run scoped scrapes using existing integrations.
3. Automatically build candidates while keeping release reviewed.
4. Enable automatic releases for proven recipe/provider families.
5. Expand repair types only after representative evidence supports them.

**Exit gate:** at least three unfinished companies with distinct source structures complete sequentially, including a shared-adapter regression, with fresh company context and no manual prompting. Exercise restart at each boundary, duplicated events, lost Jetson connection, budget exhaustion, source drift, user pause and rollback. Include one external-block case that is correctly held while another company proceeds.

## Acceptance demonstration for the complete system

1. Add a company whose source already works: only that company is scraped and applicable jobs are saved.
2. Add an unsupported company: initial failure creates one repair; AI/Python builds and validates it; release triggers the scoped retry; jobs are saved.
3. Break a known integration in a controlled test: a normal scrape records the regression and the same recovery chain fixes it.
4. Simulate a provider outage/access block: the system retries or holds appropriately without inventing a code repair.
5. Interrupt and restart the coordinator: it resumes from receipts without duplicate inference, installation or job writes.
6. Change or pause the company while work is queued: stale work cannot install or write against the new identity.
7. Run multiple companies sequentially and verify context reset, cumulative attempt accounting, visible exceptions and continued progress.

The final demonstration must run through the actual event-to-storage path. The number of passing unit tests alone is not the completion criterion.

## Recommended development order

Build Milestone 1 first: it establishes the final delivery path every subsequent feature needs. Then implement intake and failure events (2–3), wire the bounded repair process (4), automate the proven validation/release/retry gates (5), and qualify unattended operation (6). Keep broad automatic releases disabled until the complete chain passes.

This is several development milestones, not one switch. The largest uncertainty is how many source structures the small Jetson model can handle through strict recipes and bounded proposals. Queue automation cannot by itself fix that capability limit; unsupported cases need a visible engineering path.

## Source evidence reviewed for this plan

- `src/job_search_helper/engine.py`, `start_cycle`: company selection, active-company scope and unfinished-cycle constraints.
- `src/job_search_helper/cli.py`: scoped cycle invocation.
- `src/job_search_helper/runner.py`: current normal start behavior, sync and no persistent watcher after exit.
- `dev/wrapper-coder/tools/coordinator_store.py`: durable tasks, receipts, inference records and campaign state.
- `dev/wrapper-coder/tools/coordinator_campaign.py`: current live-validation and installation operator gates, budgets and outcome reconciliation.
- `dev/wrapper-coder/tools/import_integration_backlog.py`: existing backlog import mechanism.
- `dev/wrapper-coder/README.md` and `docs/jetson-wrapper-installation.md`: host-only development and delivery requirements.
- `temp/pilot-repair-20261118/SAMTEC_RESULT.md` and Samtec final QA artifacts: verified bounded pilot and its limits.

No live queue, scraper, Jetson setting, database record or production integration was changed to prepare this roadmap.

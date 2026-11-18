# Automatic company scraping and integration repair — development roadmap

Prepared 2026-11-18. This is a development plan, not activation of unattended work.

## Coordinator restart card — maintain at every checkpoint

**Role:** You are the senior engineering coordinator and release owner for Job Search Helper integration automation. You own this roadmap, task assignments, evidence review and completion decisions. Implementation workers own bounded changes; an independent QA worker verifies acceptance. Keep Jetson inference to one lane.

**Current project status:** PLANNED — this development project has not been started by preparation of this handoff. The preceding Samtec pilot is complete; it does not complete this roadmap. Verify live state before assuming these facts remain current.

**Current focus:** Milestone 1, the complete company-only scrape-to-storage path. First inspect the current repository, active scrape/writer locks, coordinator controls and saved receipts; then identify the smallest implementation gap.

**Active development workers:** None assigned by this handoff. Discover any surviving workers or processes before assigning new work.

**Last verified baseline:** Samtec pilot passed two 148-job live inventories and 60 installed tests on 2026-11-18. Pilot implementation and QA were backed up through commit `5dc9511`; the initial automation roadmap was backed up in `042d3f9` on `backup/wrapper-pilot-20261118`. Counts, installed hashes and queue controls require fresh verification. The pilot did not prove the complete company-event-to-normal-storage chain.

**Immediate next action:** Start or resume a persistent goal whose objective is all six milestones below; reconcile current state and assign independent implementation and QA work for Milestone 1. Do not reopen the completed pilot goal or substitute another objective silently.

**Goal and timer:** Record the actual goal ID/status and start time here when created. No arbitrary token or elapsed-time limit is requested. Track elapsed time. Keep per-attempt resource limits separate from the overall development goal.

**Pending decisions/blockers:** No implementation blocker established yet. The authoritative intake source and safe scheduling boundary must be confirmed from current code/configuration. External site blocks are explicit exceptions, not proof of broken code.

**Resume instructions:** Read this card and the current milestone's acceptance gate. Verify active owners, processes, locks, source hashes and latest receipts. Reconcile unfinished actions before retrying them. Resume the next unmet gate; do not recreate completed work or reset budgets. Update this card with your current coordinator role/focus, assignments, evidence and next action before dispatch and after each meaningful result.

The coordinator maintains this card as a short current snapshot, replacing stale entries rather than appending contradictory current-status paragraphs. Put chronological detail in a separate progress log. After a context reset, rereading this card restores the coordinator's role and current responsibilities; it does not authorize scope expansion or override the user's instructions.

## Development team and execution contract

- The main ChatGPT/Codex agent is the coordinator. Use up to three worker lanes when independent work warrants it and capacity permits: implementation of scraping/intake, implementation of coordinator/repair/release, and independent QA. These are development lanes on the assistant side, not additional Jetson inference lanes. Start fewer workers when dependencies leave no useful parallel work.
- Assign each worker an ID, role, milestone, owned files/worktree, deliverable, acceptance checks and dependencies. One worker owns any given file at a time. Shared dispatcher/schema edits have one explicit owner; other workers supply findings or patches for integration.
- Keep a task ledger in this folder with status, owner, latest evidence, blocker and next action. Check worker progress at meaningful boundaries and on missed checkpoints; use appropriate waits rather than busy polling. Reassign stale work only after reconciling ownership and unfinished side effects.
- Give user-facing updates about every five minutes, and promptly for failures, major milestones or required decisions; follow the app's more frequent commentary requirements during active work. Use supported progress automations only when available. A goal timer records persistent intent and elapsed time; do not promise execution while the app/host is unavailable.
- Persist state after each accepted change or failure and before context exhaustion, pause or handoff. Do not rely on a model recognizing its context limit at the last moment. Save goals, task state and receipts incrementally; never save private chain-of-thought.
- Keep the development source of truth in this roadmap on MuleLab. All scratch work and receipts belong inside the Job Search Helper development/temp folders. Publish sanitized source, tests and plan updates to GitHub at meaningful checkpoints without committing unrelated dirty files, credentials or private runtime data.
- Extend the existing Python coordinator. Each runtime company task gets fresh model context; its durable attempts and budgets remain intact. Python controls progress and validation independently of the model.
- Implementation authorization covers this roadmap, tests, bounded real-company pilot runs, supported normal storage/synchronization and guarded deployment of verified changes. Roll out automatic releases only for families that have passed the defined gates. Do not drain the historical backlog or enable unqualified repair types merely to demonstrate activity.
- Preserve manual decisions, existing Opportunities, unrelated edits, active scrape cycles and locks. Deliberately broken integrations and synthetic company records belong in isolated test environments, not the production database. Use real eligible companies for scoped production demonstrations.
- Stop on a user pause. For a genuine external blocker, preserve evidence and continue independent work where possible; if no useful in-scope work remains, report exactly what is blocked and the smallest required user action. Follow the goal tool's rules for terminal status. Never fabricate success to close a timer.

## Development completion contract

The development goal is complete only when all six milestone gates and the end-to-end acceptance demonstration pass for the declared supported integration families; independent final QA approves the actual deployed version; the company-specific scrape-to-storage and synchronization outcomes are verified; restart/duplicate/rollback behavior is tested; operator status/pause/resume documentation is usable; and source, tests, roadmap and QA reports are backed up to GitHub.

A system that correctly holds an externally blocked or unsupported company can pass that exception-handling test. That company itself remains incomplete. Completing this development project does not mean every company in the historical backlog is fixed, or that the Jetson can autonomously invent integrations for arbitrary websites.

If final QA fails, create a new QA report with reproducible findings, severity, affected version and unmet acceptance criteria. Assign new bounded repair tasks and rerun the affected checks plus the final acceptance gates. Do not erase failed reports, lower the gates or count fixture-only success as live delivery.

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

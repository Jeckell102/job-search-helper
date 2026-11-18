# Integration campaign coordinator QA — 2026-11-18

**Verdict: do not enable unattended campaign operation yet.** The deployed system is a healthy, paused offline-development prototype. Its fresh per-company context and normal single-worker service lock work, but campaign selection, pause controls, company identity, and acceptance boundaries still have reproducible gaps. The previous description of the coordinator as “ready” was too strong.

This was a read-only deployment assessment with independent scheduling and roadmap reviews. All adversarial reproductions used disposable repositories and databases. No production integration was started; no service, queue control, scraper source, or production task record was changed. The only persistent additions are this QA report and its synthetic evidence.

## Verified current state

- MuleLab coordinator: healthy, worker alive, zero snapshot errors, zero recorded service restarts.
- Jetson orchestrator: active, zero recorded service restarts. Its actual command forwarder returned the MuleLab campaign status successfully.
- Controls: queue OFF, autopilot OFF, pilot unset; no RUNNING, QUEUED, or PAUSING tasks.
- SQLite quick_check: `ok`; zero unfinished tool receipts.
- Backlog: 102 untouched eligible integrations; current structured records contain no detected conflicting company identity or duplicate company IDs. The report below describes reachable failure paths, not corruption already observed in this backlog.
- Installed unit suite: **144 test executions passed**. The new reproductions below reveal cases outside that suite's coverage.
- Staged, installed, and GitHub-backup host Python files match byte-for-byte. The remote backup branch was verified at `89a563dc7cf2105d3470bff10bfed7e93ca08d5b` before adding this QA report.
- Real process-owner test: the first coordinator acquired the lock; a separately spawned second process was rejected with `Another coordinator process owns the scheduler.`
- Fresh-context behavior: each selected integration receives its own run identity, counters, receipts, workspace, and model packet. Model messages are rebuilt from that task's receipts. The Jetson wrapper-inference endpoint passes only the supplied packet to the shared inference gate; it does not load another company's chat history.
- Completed-action recovery requeues; unfinished tool-intent recovery pauses for inspection. Tool execution is blocked when a pause wins before its atomic intent begins.

## Findings

### 1. High — campaign selection overrides an individual pause and is not limited to campaign members

`host/coordinator_store.py:137-153` selects generic PAUSED/baseline records without distinguishing campaign holds from an explicit user pause. It clears `stop_requested` when selecting one. The reproduction created an untouched task with `stop_requested=True` and `reason='Pause requested.'`; selection changed it to QUEUED and cleared the flag.

The existing backlog was intentionally paused for the earlier pilots, so a deliberate initial release must migrate those holds explicitly. The current representation cannot preserve a later decision to exclude a particular company.

Separately, `host/coordinator.py:388-397` enables and claims from the generic queue. With one unrelated direct task already QUEUED and one held campaign task, autopilot claimed the unrelated task and left the campaign task held. There is no campaign-membership key.

**Required correction:** introduce explicit campaign membership and separate HELD_FOR_CAMPAIGN, USER_PAUSED, and EXCLUDED dispositions; claim only the selected campaign member. Preserve explicit user pauses.

Evidence: `check_campaign.py`, `campaign-results.jsonl`.

### 2. High — pilot and autopilot can be enabled together

The autopilot and queue settings share a transaction, but pilot startup at `host/coordinator.py:282-326` performs its checks and writes outside that transition. Two concurrent command requests can pass the pilot checks, enable autopilot, and then save the pilot. The reproduction ended with `autopilot=true`, `queue=true`, and a non-null pilot, without either request failing. Work can continue through the backlog after an operation intended to select just one pilot.

**Required correction:** validate and commit pilot, campaign, queue, and task activation as one serialized transition. The HTTP service accepts concurrent requests, so this must hold across request threads.

Evidence: `check_scheduler.py`, `scheduler-results.json` (`pilot_autopilot_race`).

### 3. High — assignment identity and duplicate-company prevention are incomplete

`host/coordinator.py:188-211` checks metadata shape, test paths, and file paths but does not bind the company ID, name, and URL to the work objective. The reproduction accepted structured metadata for Beta/COMP-0002 while the objective instructed work for Alpha/COMP-0001. The model packet contains the objective and omits the structured `integration` field, so the purported authoritative identity does not control execution. The backfill function also accepts a metadata dictionary with only a company ID.

`host/coordinator_store.py:64-79` deduplicates entire batch digests rather than company identities. Two different batches for COMP-0001 produced two eligible tasks. The documentation asks an operator to detect such overlap; an unattended coordinator must enforce it itself. The newly enriched batch files also have different digests from the original imports, so resubmitting them must not be treated as a harmless migration retry.

**Required correction:** make structured identity canonical, derive the worker assignment and evidence targets from it, validate it at activation, and enforce a unique campaign/company assignment with explicit retry lineage.

Evidence: `check_scope_and_identity.py`, `scope-identity-results.jsonl`; `check_campaign.py`, `campaign-results.jsonl`.

### 4. High acceptance gap — assigned edit scope and independent test assertions are not enforced

`host/coordinator.py:443-458` checks the workspace manifest before dispatch, but does not check whether the requested edit belongs to the assigned integration. `host/coding_tools.py:165-215` permits edits throughout the isolated source/test/document tree, except the protected protocol. A worker assigned `src/a.py` successfully changed `src/unassigned_company.py` in the reproduction.

The same real edit path accepted replacement of the assigned test's assertion with `pass`. Final offline verification runs those editable test files (`host/coordinator.py:474-480,523-530`); it has no independent acceptance assertions or check that required assertions remain intact. This does not permit production installation, but it weakens what an offline-ready draft proves.

**Required correction:** enforce an explicit file-edit scope, require a reviewed scope expansion when needed, and retain independent host-owned acceptance checks alongside editable regression tests.

Evidence: `check_scope_and_identity.py`, `scope-identity-results.jsonl`.

### 5. Medium — pause may precede a new inference call; failed pilot startup can leave controls blocked

The atomic action gate protects tools, but model reservation and dispatch at `host/coordinator.py:710-715` do not recheck control state atomically. A pause issued during budget calculation committed first; the model was nevertheless invoked with status PAUSING and `stop_requested=True`. The result was subsequently held, so the reproduction did not edit source, but the call consumed budget and a real call could delay stopping for minutes.

Pilot startup saves `pilot_task` before resume validation. A budget-exhausted task causes startup to fail while leaving the pilot slot set. Autopilot and global queue resume then reject until pilot-stop clears it.

**Required correction:** atomically check controls and reserve each inference action; validate pilot startup before atomically publishing the pilot/task state.

Evidence: `check_scheduler.py`, `scheduler-results.json` (`pause_before_model_dispatch`); independent scheduler QA reproduced the stale-slot case.

### 6. Medium — campaign completion and reporting are incomplete

When eligible work runs out, the loop continues polling with autopilot ON. There is no durable campaign result distinguishing exhausted work, paused exceptions, and offline-ready drafts. Several status paths also overstate readiness: a held batch is described as queued; start says workers continue when the global queue is paused; gate tasks display a resume command that the service rejects.

**Required correction:** persist campaign totals and an explicit finished-with-exceptions outcome, without equating offline completion with integration success. Display company names, current stage, exceptions, and the next allowed action.

Source: `host/coordinator.py:240-278,300-301,333-355,372-429`.

### 7. Additional hardening and reproducibility issues

- Direct `Coordinator.run()` bypasses the process-owner check implemented in `start()`. Production `host_server.py` uses `start()` and its lock passed the cross-process test; this is an internal entry-point hardening issue. Require ownership inside the loop as well.
- Copied root test inputs such as `pyproject.toml` and title lists are absent from the tracked source manifest and baseline Git commit. Changes to them can alter tests without source-drift detection. Include every test input in the baseline digest. Source: `host/coordinator_workspace.py:37-63`.
- The saved campaign deployment script omits the later manually installed workspace-source correction and the local Jetson-forwarder source needed by its parser test. Deployed copies are correct today, but rerunning that script alone does not reproduce the final tested installation. Source: `deploy_campaign_update.py:15-18,40-42`.

## Deliberate limits, not new defects

Live scraper validation, production installation, and delivery of generated wrappers remain operator gates. This coordinator currently produces offline drafts or explicit pauses and then advances. It cannot claim that every applicable job was downloaded or that an integration is installed.

Every workspace starts from the frozen `queue-base`, not current production. The shared dispatcher, VideoRay adapter, and both pilot test files differ from the main checkout. This preserves draft isolation but means future drafts may start before accepted pilot fixes; a reviewed baseline refresh is needed before describing them as based on current production.

No live inference or new integration was run for this QA. Tests used fake model responses and temporary files; the live checks were limited to service health, read-only status, source inspection, database integrity, and backup parity. The two earlier live pilots remain historical evidence for their own integrations, not proof of autonomous campaign completion.

## Recommended repair order

1. Define campaign membership and company exclusions; make pilot/autopilot selection and pause transitions atomic.
2. Bind canonical company identity to assignments and prevent duplicates.
3. Enforce edit scope and independent acceptance tests; include every test input in the baseline digest.
4. Add terminal campaign reconciliation and accurate user controls/status.
5. Add the reproduced cases to the automated suite; run a bounded two-company rehearsal showing a fresh worker for each, a respected user pause, safe restart, and final exception accounting. Keep live validation and installation separately gated until their own acceptance contract is implemented and demonstrated.

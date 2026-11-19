# Roadmap QA and alternative architecture comparison

**Subsequent disposition — 2026-11-18:** Following the user's request to update the documents, the roadmap and handoff now adopt the hybrid development approach and require the QA finding ledger. The original assessment below is retained as review history; references to unchanged documents or a proposed/not-yet-adopted alternative describe the reviewed versions listed below. Current decisions and status are in `AUTOMATION_ROADMAP.md`, `QA_FINDINGS_LEDGER.md` and `FINAL_ROADMAP_QA.md`. F1–F8 remain open implementation/verification requirements; revising the documents does not close them or enable automation.

Reviewed 2026-11-18. Scope: design and code inspection; no production changes, live scraping, inference requests or test-suite execution. Two independent review lanes examined the recovery contracts and alternative architecture while the coordinating reviewer inspected storage, intake and release boundaries.

## Verdict

**CHANGES REQUIRED before connecting or activating unattended operation.** The roadmap is sound as a direction and candid about the Samtec pilot's limits. Milestone 1 discovery and scoped development can proceed; resolve the contracts below before implementing their respective cross-component boundaries or activating automation.

The main issues are unspecified boundaries between otherwise sensible components. Passing tests within each component would not prove that company additions, repair releases and stored jobs cannot be lost, duplicated or associated with stale source versions.

Reviewed inputs:

- Authoritative roadmap: `/home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118/AUTOMATION_ROADMAP.md`, SHA256 `b4c55faa2fc161969391f0e132b2d0cad928e243cf5acce1e447d49534adab72`.
- Handoff: same directory, `NEW_WINDOW_HANDOFF.md`, SHA256 `6aebbc55a8cab887e0c76310c3f92e1506959cc3715bc0bab2e7d49fdb1c40df`.
- Current repository and coordinator source paths referenced below, read during this assessment.
- Samtec's reviewed recipe, which remains a fixed company-specific compiler rather than a general runtime recipe loader.

This report proposes revisions. The authoritative roadmap and handoff were intentionally left unchanged so the alternative is not silently adopted as an approved architecture.

## What passes the design review

- One Jetson inference lane, with heavy work and durable state on MuleLab.
- Reuse of the existing Python coordinator, task history, storage pipeline and locks.
- A company-only storage milestone before expanding automation.
- Separate classification of integration defects, temporary failures, access barriers and publication failures.
- Independent live evidence, guarded releases, manual-choice preservation and version-bound receipts.
- Fresh company context with durable budgets and history, plus explicit unsupported cases.
- The coordinator restart card and worker ownership model. A separate goal timer does not replace the runtime scheduler or recovery protocol.

## Findings and required corrections

### F1 — P1: Specify reliable delivery across separate databases and startup reconciliation

**Evidence:** roadmap Milestone 2 mentions a transactional outbox but leaves its owner and cross-store acknowledgement unspecified. `sqlite_repository.py:307` commits company changes in the repository transaction; `inbox.py:39` stores inventories separately; `coordinator_store.py:67` stores repair tasks separately. An audit `events` table exists in `sqlite_repository.py:120`, but its existence alone does not establish an intake event-delivery protocol.

**Failure scenario:** the company commits, the process dies before queue insertion, and no repair/scrape request is durable. Conversely, insertion succeeds but acknowledgement is lost and the event is delivered again. An initial watcher snapshot can also miss a company added between the snapshot and the first polling checkpoint.

**Correction:** declare the authoritative company record and revision rules. Put a durable outbox event in the same local transaction as each supported company mutation/import. A bridge delivers it to the existing task store using a unique event key; acknowledge only after durable consumer acceptance. Define ordered source revisions, replay behavior and a bootstrap snapshot/catch-up boundary. Reconciliation must recover edits made through supported external intake paths without silently assuming a database trigger sees remote Sheets changes.

**Acceptance:** crash before and after each commit/acknowledgement; deliver each event repeatedly; add a company during watcher initialization. Every eligible addition produces one logical request, no rollback produces work, and stale source revisions cannot replace newer ones. At-least-once transport with duplicate-safe effects is the contract; do not promise exactly-once remote execution.

The same-transaction outbox plus duplicate-safe consumers is a standard solution to this dual-write problem. It does not require adding AWS, a message broker or a new scheduler. [AWS transactional outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)

### F2 — P1: A repaired retry needs an identity that cannot reuse the failed inventory

**Evidence:** `inbox.py:53–62` deliberately uses `INSERT OR IGNORE` keyed by cycle and company, preserving pending inventory. Roadmap Milestone 5 requests a retry but does not define how the new attempt interacts with that existing key and its saved publication plan.

**Failure scenario:** the new integration fetches valid jobs, but saving under the old cycle/company key retains the earlier partial inventory. Alternatively, deleting the old payload to make room destroys its saved cursor and receipts.

**Correction:** define request, scrape-attempt, company-source revision and integration-release identities before connecting the retry path. Give the repaired fetch a distinct durable attempt and explicit precedence over earlier evidence; adapt existing cycle membership safely. Preserve pending historical payloads and plans. Do not fix this by clearing the inbox or bypassing the normal writer.

**Acceptance:** seed an old partial inventory and partially applied plan, install a repair, retry, then restart. The accepted result must reference the new attempt and release; old evidence stays auditable; no duplicate jobs, silent failed-inventory reuse or stale job closures occur.

### F3 — P1: Release and scraper startup need a shared admission contract

**Evidence:** roadmap lines 167–169 call for a release lock and fresh worker. `runner.py:420` holds a scraper lock; the supervised `guarded_install.py:24–25` checks coordinator controls. These checks do not, by themselves, establish mutual exclusion with every scraper startup.

**Failure scenario:** a scraper starts while several source files are being changed, or a worker resolves part of a new release after already using the old one. A release lock that only installers observe does not prevent this.

**Correction:** document shared admission/lock ownership and acquisition order for scraper startup and release activation. Pin the complete required code/dependency/configuration version for an entire attempt. Release immutable artifacts where practical; atomically select a version for new attempts. Existing processes complete using their pinned version. Preserve the current adapter compatibility route while introducing this incrementally.

**Acceptance:** race worker startup against release preparation/activation and rollback. Each attempt uses entirely its old or new qualified version, never mixed source. Record the version in fetch, validation and storage receipts.

Fresh processes are preferable to relying on Python module reload: existing references may retain old objects, and reload is not thread-safe. [Python importlib documentation](https://docs.python.org/3/library/importlib.html#importlib.reload)

### F4 — P1: An unknown Jetson outcome requires reconciliation, not simply moving to the next company

**Evidence:** roadmap lines 52, 177 and 191 promise continued progress and lost-connection recovery. `coordinator_inference.py:124–130` marks transport/malformed-response failures `UNCERTAIN` and disables scheduling controls. `coordinator_campaign.py:176–186` treats unresolved inference as a global blocker; `coordinator_store.py:888–905` preserves the operator recovery boundary.

**Failure scenario:** a request executes on Jetson but its response is lost. Retrying on timeout can duplicate inference work, leave multiple outstanding requests, or misattribute usage/results. The existing Jetson gate serializes inference; this review does not establish simultaneous model execution. Leaving every such incident permanently manual defeats unattended operation.

**Correction:** define durable request IDs, remote status/result retention, ownership generations and acknowledged completion/cancellation. Reconcile the original request and conservatively settle its budget before allowing another inference. A company-specific access block may be skipped; an unknown shared inference outcome holds that lane until resolved. Safe non-inference work may continue.

**Acceptance:** disconnect after the remote model has started, then restore connectivity. Prove no second inference overlaps, the original outcome is accounted for once, and another company's inference proceeds only after safe resolution. If the device cannot be reached, report a device-level hold, not a repaired company or an idle lane.

### F5 — P1: Freeze the initial supported scope and prove the model's role before broad automation

**Evidence:** the completion contract permits declared supported families, while Milestone 6 asks for three distinct source structures. The initial family list, candidate companies and allowed autonomous edit classes are not fixed. The Samtec recipe accepts one approved eight-field selection, binds COMP-0739 and emits source edits against one exact input hash. It does not yet discover arbitrary mappings or execute generic versioned configurations.

**Failure scenario:** development discovers that only one hand-prepared recipe works, then quietly narrows the supported list or counts already solved integrations as autonomous repair success. Alternatively, a new site triggers code release beyond the capabilities actually demonstrated.

**Correction:** before building the general loop, record an acceptance matrix with named pilot companies, source structures, currently broken behavior, permitted repair type, expected AI contribution and engineering escalation boundary. Preserve failures and coverage results. Deterministic cases should avoid unnecessary inference; ambiguous supported cases should demonstrate bounded AI decisions from public evidence without per-company manual code supplied during the acceptance run.

**Acceptance:** predeclared examples cover existing-adapter reuse, a real recipe/configuration repair and a controlled regression, with the roadmap's distinct-structure requirement explicit. Cases requiring new executor behavior remain engineering work until that behavior is independently qualified. Scope changes are recorded and cannot silently satisfy a broader goal.

### F6 — P2: Define local-save versus publication completion precisely

**Evidence:** the roadmap distinguishes saved jobs and pending synchronization, but does not define the final receipt that completes a request. `run_sync.py:254–255,391–403` can retain pending writes and a final error. Aggregate counts can include unrelated backlog or repeated updates.

**Correction:** define separate durable `LOCAL_COMMITTED`, `SYNC_PENDING` and `SYNC_CONFIRMED` outcomes, bound to request/company/source/release and exact record identities. A scrape can release its worker after local persistence while publication retries independently. Final system acceptance must include both a confirmed real synchronization and a recoverable pending-sync scenario. Preserve intervening manual decisions.

**Acceptance:** force loss of the remote acknowledgement after a successful write. Reconcile exact destination records and replay safely without fetching jobs again or declaring success from aggregate row counts.

### F7 — P2: Bound company-only queue waiting during unfinished main scans

**Evidence:** `engine.py:415–435` rejects a new scoped cycle while an unfinished cycle exists. `runner.py:219–234` uses an explicit fresh-full-scan path. Milestone 1 says to wait for a safe boundary but does not specify which boundary or whether an indefinitely paused old cycle blocks all new companies.

**Correction:** define the initial scheduling behavior explicitly: serialize at a documented boundary, show queue age and the blocking cycle, and provide a recovery path for paused/stale cycles. Do not use the full-scan supersession path to squeeze in a single company. Decide and measure an acceptable intake-to-start target under idle and busy conditions.

**Acceptance:** add a company during an active scan and during an old paused cycle. It must neither trigger a full rescan nor remain silently stuck. Resume/cancel policies must preserve existing cycle and writer ownership.

### F8 — P2: Specify unattended service operation and evidence retention

**Evidence:** the plan covers task restarts and saved receipts but leaves service startup, offline catch-up, disk limits, evidence retention and runtime support-matrix visibility as implementation assumptions. Existing host services reduce the amount of new work but do not establish these guarantees for the new intake-to-release chain.

**Correction:** extend existing supervised services; document boot/reconnect behavior, one-instance ownership, intake catch-up, shutdown/pause semantics and disk-pressure handling. Protect unacknowledged events, active releases and recovery receipts from cleanup. Keep durable state in the application's maintained state area; temporary development Markdown is a human-readable checkpoint, not the production scheduler database.

**Acceptance:** reboot/reconnect and simulated disk pressure leave no lost requests, duplicate owners or discarded uncommitted evidence. The system reports which release families are automatic and which need engineering review.

## Compare the two approaches fairly

### A — Current roadmap: workflow-led integration repair with source releases

Connect company events, failures and storage to the existing coordinator. Use adapters and reviewed recipes first, allow bounded code proposals where qualified, then test and install source changes into the scraper.

This already includes recipes; it is not a plan for unrestricted model coding. Its main advantage is reuse of today's dispatcher and integrations. Its main cost is managing source changes, shared-provider regressions and deployment races whenever a repair changes executable behavior.

### B — Alternative: stable executor with immutable integration configurations

Keep the scraper's execution behavior in tested provider executors. Store each company's integration as a versioned configuration that selects only capabilities those executors support. Python discovers known providers and permitted candidates; Jetson interprets ambiguous evidence and selects among bounded options. The validator independently checks the resulting configuration against actual public jobs.

A configuration contains a company/source binding, executor version, permitted listing/detail/pagination behavior, limits and evidence references. It contains no Python, arbitrary expressions, unbounded URLs or acceptance-rule overrides. URL scope, pagination ceilings, full-description checks and identity validation remain enforced by the executor. Configuration itself is not automatically safe or correct.

Release activation selects a verified immutable version for new attempts. Each attempt pins that version through fetching and storage. An unfamiliar website requiring a new capability creates an engineering task to extend an executor or adapter; it does not turn configuration into an unrestricted programming language.

| Criterion | A: Current source-release workflow | B: Versioned configuration/executor workflow |
| --- | --- | --- |
| Reuse of current implementation | High; most adapters already expose the expected interface. | Existing adapters can remain, but a configuration schema, resolver and executor interface must be added. |
| Fit for the small Jetson model | Good for constrained recipes; less dependable for precise novel Python changes. | Better for bounded interpretation and selection; not a guarantee of correct selection. |
| New website structures | Can propose custom code, subject to successful tests/review. | Limited to implemented executor capabilities until engineering extends them. |
| Routine release impact | May alter shared Python files and require broad regression coverage. | Often a company-specific version selection; executor upgrades still need broad code review. |
| Rollback | Restore a compatible source release without clobbering newer changes. | Restore the prior configuration selection for future attempts; retain compatible executor versions. |
| Initial implementation cost | Lower for an additional supervised source-patch pilot. | Higher initial contract/loader cost; no evidence yet for a numerical time saving. |
| Reproducibility | Requires pinning code, dependencies and source identity. | Requires pinning executor, configuration, dependencies and source identity. |
| Intake, queue and storage reliability | All eight QA findings still need resolution. | All eight QA findings still need resolution. |
| Proved by Samtec today | Fixed selection plus trusted source generation and supervised validation. | General runtime configuration loading and automatic release are not yet proved. |

## Recommendation: use A's existing workflow and B's stricter routine release boundary

Keep the six-milestone business workflow and existing Python coordinator. Make reviewed, versioned configurations the default unattended repair unit for qualified provider families. Retain bounded source-code repair as a separate reviewed engineering path, with a new capability becoming automatic only after qualification.

This offers a better fit for the observed Jetson limitations without discarding the scraper or pretending configuration can handle every website. Do not build a second queue, require new cloud infrastructure or migrate the entire adapter library up front. Begin with one compatible executor/recipe family alongside the existing routing path and extend only after the end-to-end loop is proved.

Challenge to this recommendation: a package registry can become a second complex framework, and an overly expressive schema merely hides code inside configuration. If one prototype cannot reuse the existing `fetch_inventory` interface and normal transport/storage contracts with a small explicit schema, do not force all adapters through it. Keep current adapters, constrain automatic repair to reviewed source templates temporarily, and retain the same versioning and release gates.

## Proposed roadmap adjustment before development

1. Add short design-contract checkpoints for company/source identity, event ownership/acknowledgement, attempt identity, release admission, inference reconciliation, publication receipts and the initial support matrix. Resolve the contracts relevant to each implementation boundary before parallel workers depend on it; F1–F5 must be closed before unattended activation.
2. Keep Milestone 1: prove a normal company-only storage/sync path using a current working integration.
3. Build one minimal full path across Milestones 2–5 for a predeclared repair case: event, failure, configuration selection, independent validation, guarded activation, fresh scrape and verified storage. Initially trigger that event explicitly in an isolated test rather than importing the backlog.
4. Expand automatic intake and failure classification after that full path works. Prove duplicate, stale-source and watcher-bootstrap cases before enabling the continuous watcher.
5. Qualify the named diverse company cases, shared-provider regression and unknown-inference recovery. Keep engineering-only capabilities clearly separated.
6. Run final independent QA, including all failure boundaries; activate only the proved automatic scope and back up the deployed version and reports.

Suggested engineering ownership after those contracts are agreed: one worker for intake/attempt/storage contracts, one for recipe/resolver/release contracts, and one independent QA worker. The ChatGPT coordinator owns integration decisions and the plan. Jetson remains one inference lane.

## Next decision

Adopt the hybrid release boundary and amend the roadmap/handoff with these explicit contracts before connecting or activating unattended operation. Scoped Milestone 1 work can start immediately. This assessment itself does not adopt the alternative, authorize new runtime behavior or enable any queue.

## Evidence and limits

- Primary local evidence: roadmap/handoff above; `src/job_search_helper/{engine.py,runner.py,inbox.py,sqlite_repository.py,run_sync.py}`; `dev/wrapper-coder/tools/{coordinator_store.py,coordinator_inference.py,coordinator_campaign.py}`; supervised Samtec recipe and guarded installer.
- Independent lanes reviewed recovery/acceptance contracts and architecture tradeoffs. Their findings were checked against the local source reads described above.
- External references support specific design principles, not a claim that this repository implements them: [transactional outbox and duplicate handling](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html), [Python reload behavior](https://docs.python.org/3/library/importlib.html#importlib.reload), and [SQLite transaction atomicity](https://www.sqlite.org/atomiccommit.html). SQLite transaction atomicity does not by itself make independent database, HTTP and file-install operations one atomic unit.
- This is a static design assessment. It does not certify live process state, current remote job counts, race-test results, performance, autonomous coverage or deployment readiness.

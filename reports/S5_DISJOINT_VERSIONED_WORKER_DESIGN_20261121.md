# Bounded side-by-side worker / attempt version — design verdict

**PROCEED AS AN ISOLATED DESIGN; not currently supported or authorized for execution by existing source.** A complete immutable qualified worker tree can, in principle, run one truly disjoint owned Company attempt against the canonical stores, serializing through the same normal locks, while canonical source and its NO_RELEASE admission remain unchanged. This directly implements the roadmap's attempt versioning requirement rather than clearing, rewriting, or retroactively versioning Saronic. It requires a small cross-component authority extension; merely launching a copied checkout is unsafe and is rejected.

Read-only scope: production/staged source and saved roadmap only. No application execution, database reads, provider or other network requests, service/lock changes, or source modifications. Existing code observations below are current file reads; feasibility remains an inference pending implementation and independent QA.

## Why the design is bounded, and why it does not work as-is

The roadmap `AUTOMATION_ROADMAP.md:85` explicitly requires pinning complete configuration/code/dependency versions per attempt and activating validated versions only for new attempts. Existing `Engine.start_cycle` stores `runtime_binding` in State (`engine.py:715–716`), mirrors it in Scan Cycles Notes (`engine.py:895`), and validates exact equality on resume (`engine.py:843–859`). Exact event publication re-derives Company/request/source/runtime authority from the admitted observation (`exact_cycle_receipt.py:76–113`). These are reusable enforcement seams.

But all current release authority is global: `release_admission_bootstrap.py:150–198` selects `state_root/integration-release-journal.json`; `integration_release.py:245–273` requires the same active COMPLETE journal for a repair retry; `scan_request.py:63–86` then rejects unfinished blockers; `engine.py:861–876` rechecks that global authority. The staged controller repeats the global journal/receipt/intent check (`release_controller.py:105–121`) and exact runtime/Company ownership (`182–214`). `qualified_release_owner.py:72–95` deliberately prohibits replacing source with unfinished work. **Keep that replacement prohibition intact.**

A copied worker pointed at canonical State still observes canonical NO_RELEASE. Inventing COMPLETE in an environment variable, pointing the worker at a private replacement State directory, or overwriting the canonical global release journal would not establish the required authority.

## Minimum durable authority

Add one immutable, independently approved attempt-release record, outside the canonical global release journal. It must bind:

- the exact qualified release manifest and approval/custody receipt, complete worker source/configuration/dependency digests, immutable worker root and actual measured executable/import source;
- exact request ID, predecessor failure/outcome receipt, Company ID, source revision, fresh repair attempt ID and ultimately its one cycle ID;
- exact canonical State/Jobs/Inbox and workbook identities, canonical scraper/writer lock identities, and the inherited protected historical scope digest;
- the raw unfinished-cycle membership proof that this Company is absent everywhere, plus no conflicting selected-Company saved inventory, plan, receipt, active cycle or review claim;
- durable preparation/admission/terminal status and the exact final publication/outcome receipt references. Ambiguous or interrupted authority is held; it never silently changes the global release journal.

Reuse existing full release binding and canonical retry identity formats where possible, but **do not silently redefine their global-active-release semantics**. The worker needs an explicit scoped authority reference, persisted in the admitted cycle/Notes and verified on every resume and publication. Whether represented by a new runtime kind or a separate mandatory scope record, the design must make an unscoped copied COMPLETE binding insufficient. `runner.py:39–62` currently accepts only NO_RELEASE/COMPLETE/ROLLED_BACK and exact fields, so any new runtime kind requires deliberate validation changes rather than extra environment fields.

## Exact minimal seams / ownership

| Seam | Required bounded change or reuse |
|---|---|
| Stable bootstrap / measured launcher | New exact worker entry verifies qualified immutable artifact and the attempt authority **before application import**, acquires the canonical scraper lease, pins canonical store layout, and execs only that measured worker. Reuse existing bootstrap lock inheritance and complete tree measurements (`release_admission_bootstrap.py:233–289`); generic launcher stays unchanged. |
| Qualified owner / release admission | Add attempt activation of an immutable artifact, distinct from `activate_release` copying into canonical source. Reuse independent qualification owner checks, manifest/receipt custody and limits. Global replacement guard stays intact. Artifact can be retired only after its attempt is terminal; an unfinished attempt keeps its exact artifact for restart. |
| Request / cycle validation | Add one typed route for the exact qualified disjoint request; retain ordinary global blocker behavior. Reuse `retained_operator_scope.disjoint_event_scope_evidence` (`:22–49`) and historical-work sealing (`:61–92`) where applicable. They inspect raw unfinished membership, including superseded scope. The existing helper expects one effective blocker; do not broaden that. Recheck under normal locks before admission, provider work, and publication. |
| Engine / retry controller | Centralize explicit scoped-vs-global authority selection for this entry; keep `assert_active_release_binding` strict for existing callers. Persist the measured worker runtime and authority digest with the new cycle. Use the existing exact one-company local engine execution and publisher, not normal broad startup/pipeline hooks. |
| Receipts / exact publisher | Preserve exact request/attempt/source/runtime/Company bindings, sealed operations and readback acknowledgement. Extend only the authority verification needed for the scoped record. Reuse canonical stores and exact selected Sheet writes; no global sync, other cycle closure, review purge, manual-opportunity import or broad dirty drain. |

No second scheduler, no second inference lane, no copied live stores, no schema migration of canonical tables, and no change to the old cursor or runtime binding are required by this design. Reject or separately review any implementation that introduces those as prerequisites. Whole-file SQLite hashes may change from the permitted new attempt; protection must compare the exact retained logical rows/plans/receipts, not claim that canonical database bytes never change.

## Smallest independent proving gate

One disposable composition must start with an unfinished legacy cycle with a partially applied plan and no runtime binding, canonical NO_RELEASE, and an unrelated owned Company failure. Admit the qualified full worker tree, fetch once, publish only its exact rows with one matching durable receipt, and finish its own cycle. Restart before/after each durable attempt admission/publication boundary; prove no repeated remote write and exact worker reuse. Compare original cycle, cursor, inventory, plans, receipts, Jobs and protected dirty fields unchanged, and verify canonical bootstrap still yields its original NO_RELEASE identity. Refuse an overlapping Company, changed Company revision, changed worker bytes, missing scoped authority, wrong store/workbook, and an attempt to execute the old cycle using the new worker. Existing locks must refuse a concurrent ordinary writer.

This is a design gate, followed by independently reviewed implementation, disposable proof, and a separately bounded native attempt. It does not claim deployed acceptance.

## Current applicability limit

A truly disjoint owned Company/failure is a mandatory input. This design does not make Amphenol, Draper, Allen, Forterra, or any other Company already in the retained raw scope eligible. Existing selected-membership permission is not equivalent to disjointness. If all currently named acceptance cases overlap, either an explicitly documented qualifying disjoint case is needed or retained recovery remains necessary for those cases. There is no new reason to force a provenance choice for Saronic merely to prepare this design.

Coordinator update received after the source review: the independent origin audit found **zero pending events and zero disjoint cases in the frozen accepted set**. Therefore this design cannot run today, cannot clear any current named-case gate, and is not the immediate native qualification path. It is a bounded future implementation option only. No additional data read was performed by this lane.

Source roots used: installed `/home/chris/job-search-helper_old/src/job_search_helper/`; staged qualified-owner/controller/bootstrap `/tmp/jsh-s5-release-controller-join.20261121/`; roadmap `/home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118/AUTOMATION_ROADMAP.md`.

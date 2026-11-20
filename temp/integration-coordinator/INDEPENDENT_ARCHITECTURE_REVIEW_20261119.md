# Independent architecture review: retained-work company intake

Review date: 2026-11-19 America/New_York; evidence collected through 2026-11-20 UTC.

**Decision: REDESIGN THE ORCHESTRATION; REUSE THE EXISTING CORE. Do not promote the recovered candidate to production.**

A distinct, local-only company-intake entry point and durable ownership domain are necessary while the historical cycle is retained. A second implementation of filtering, deduplication, absence handling, job storage, or publication receipts is not necessary. Keep useful admission/journal components; replace their ordinary-cycle handoff. Do not discard the whole project or rewrite the scraper.

This is a review, not implementation or release approval. The review team changed no production source, job data, Google Sheets, locks, queues, services, or GitHub. Tests and reproductions used disposable fixtures. This report is the only project artifact written by this review. This review did not resume development, a goal, or a timer; it cannot attest to unrelated tasks' activity.

## 1. Evidence, baseline, and limitations

Read completely: production `NEW_WINDOW_HANDOFF.md` and `AUTOMATION_ROADMAP.md`; the current 1,628-line `COORDINATOR_STATUS.md`; and the handoff's referenced QA ledger/final-roadmap/approach-comparison reports.

Two requested design files and `/tmp/jsh-retained-work-runner-candidate` are **absent at their requested locations**. The complete historical design texts were instead read from their original recorded tool outputs, plus the complete mandatory-feasibility amendment:

- `RETAINED_WORK_EXCEPTION_DESIGN_20261119.md`: recorded output at `2026-11-20T00:49:51.655Z`.
- `RETAINED_WORK_RUNNER_INTEGRATION_DESIGN_20261119.md`: recorded output at `2026-11-20T00:53:24.085Z`; amendment patch at `2026-11-20T00:56:15.899Z`.
- Source record: `/home/chris/.codex/sessions/2026/11/18/rollout-2026-11-18T19-06-00-01a1f11f-e014-7493-8441-2f66502e23a9.jsonl`.

These are historical design evidence, not proof of the missing files' final contents. No missing candidate was reconstructed or installed during this review.

The current restart card says temporary storage was cleared and an earlier runner was recovered from session patch records. The available source is in the isolated feature checkout at commit `8f27b8511d5c560cd711ed73b23eeed9eb5399da`; it was clean at the initial checks. That recovered runner does **not** implement the later separate frozen-preflight journal described in the review request. Findings below distinguish the recovered source from the unavailable paused version. The card's earlier source acceptance does not establish acceptance of either version against the new reproductions.

At final verification, concurrent changes appeared in feature `exact_local_plan.py` and `sqlite_repository.py`, plus new `retained_dirty_provenance.py` and `test_retained_dirty_provenance.py`. These were not authored by the review team, were left untouched, and are **not accepted or assessed by this report**. The production hashes and recovered runner/exception hashes below define the assessed baseline; any new implementation needs a separate pinned diff and QA. Establish a single owner before continuing integration.

Production HEAD is `c9db537d76dcb4dc22ace5d6342adc35c1085688`, with substantial existing tracked and untracked changes. HEAD alone does not identify the production source reviewed. File hashes are recorded in section 12. Future integration must be a narrow patch against these current production interfaces, not an overlay of the feature tree.

Fresh read-only local evidence confirms `CYC-B639C6D864EC` is `In Progress`. Samtec `COMP-0739` is in its membership at stage `queued`, with zero saved inventories and zero sync plans for that company in that cycle; its item has no `staging_complete`, `next_job_index`, or saved `jobs` field. This is not proof that all possible claims, receipts, or shared records are absent. The Saronic provenance conflict remains an explicit hold; this review did not settle it.

No Google or provider access, real-company run, deployed-system QA, service-state acceptance, or GitHub-backup verification was performed. Cached local workbook controls are not a fresh Google read. Existing operational and backup claims in the card remain historical evidence, not newly verified claims here.

### Fresh isolated tests

| Selection | Result | Meaning |
|---|---:|---|
| Feature `test_retained_work_exception.py`, `test_retained_work_runner.py` | 31 passed, 3.83 s | Existing recovered-candidate tests pass; additional reproductions below still fail isolation. |
| Production `test_exact_local_plan.py`, `test_exact_cycle_planner.py`, `test_batching.py` | 54 passed, 5.53 s | Existing planner/chunk mechanisms are useful reuse candidates, not end-to-end acceptance. |

Tests used `PYTHONDONTWRITEBYTECODE=1`, explicit source paths, `pytest -q -p no:cacheprovider`, and temporary fixtures. Three independent lanes reviewed candidate admission, production reuse, and publication/provenance. No lane owned production edits.

## 2. Blocking findings

### F-A — Frozen source/provider identity is not tied back to durable admission

Recovered `retained_work_runner.py:373-399` verifies the admission and trusted snapshot, but does not derive the admitted identity again from the inventory being consumed. The original identity is sealed in `retained_work_exception.py:695-701`. `PreparedExceptionalStart` is frozen only at its top level; its dictionaries remain mutable. Journal self-hashes do not close this gap.

Two disposable-fixture reproductions succeeded incorrectly:

1. Prepare an allowed request; change `prepared.inventory['source_url']` and `['ats']` to the historical source/provider; commit. Observed: `IN_MEMORY_SOURCE_CHANGED_COMMITTED LOCAL_INVENTORY_FROZEN https://api.example.com/old`.
2. Interrupt after reservation; change those fields in the persisted start-journal inventory and recompute its `inventory_digest`, `binding_digest`, and `prepared_digest`; leave the separate admission and authorization untouched; cold recover and commit. Observed: `PERSISTENT_SOURCE_CHANGED_RECOVERED_COMMITTED LOCAL_INVENTORY_FROZEN https://api.example.com/old`.

Readback validates a self-consistent substitution rather than the identity actually admitted. This corroborates the class of QA finding in the user request, but is a fresh reproduction against the recovered baseline, not a claim to have tested the missing later journal.

### F-B — Last validation and local ownership commit are not one protected transition

Recovered runner validates at `460-465`, then constructs writers at `476`, and saves State at `490`. The later check at `518-519` covers the historical manifest, not the entire live request/company/admission tuple. A fixture changed the Company to `Inactive` inside the writable-State factory; commit still returned `LOCAL_INVENTORY_FROZEN`.

A final extra unlocked read is insufficient. Establish a shared lock/transaction protocol and compare the current authority inside the transition that commits ownership. Require a generation/fencing check at each later mutation. The normal scraper and publisher use different locks (`runner.py:668`; `run_sync.py:480`), so owning the scraper lock alone does not exclude publication or every local reviewer.

### F-C — Recovered “isolated” inventory is discoverable by ordinary consumers

Recovered runner writes ordinary State at `490` and ordinary inventory at `509`. Production `InventoryInbox.save` likewise inserts an unblocked row (`inbox.py:302-315`). Fixture checks returned:

```text
NORMAL_INBOX_CYCLES_INCLUDE_EXCEPTION True
NORMAL_INBOX_PENDING ['COMP-NEW']
```

No source consumer outside that runner recognizes its `retained_work_exception` marker. Production `LocalPipeline.run` (`local_pipeline.py:538-562`) and `Engine.resume_parallel` (`engine.py:1221-1240`) can consume ordinary saved inventories. `publication_deferred` is advisory, not isolation. Fixing F-A alone is not release acceptance.

### F-D — Shared dirty data has no enforced request-owned publication hold

Production `dirty` rows identify only tab, row, and header (`sqlite_repository.py:113-115`, `339-344`). The generic synchronizer discovers them globally (`sheets_sync.py:430-448`). A new local-only command cannot prevent another command from publishing its later shared-DB mutations.

Before shared job writes are enabled, atomically bind each owned mutation to a durable delivery hold that **all** publishers respect. Exact-local `dirty_before` evidence is useful audit material, not such a hold. A row label, Company pause flag, ordinary claim, or a receipt in another database is insufficient.

### F-E — Samtec is not eligible for the existing bridge-only, outside-membership exception

Recovered exception requires authentic bridge request/receipt provenance at `624-652` and rejects any historical membership at `672-673`. Samtec is a member. It cannot be made eligible by inventing a bridge event or merely adding operator provenance. Section 8 defines the two honest alternatives.

## 3. Correct architecture boundary

The narrow path should be:

```text
one authenticated/provenanced request
  -> provisional isolated Company/request reservation
  -> existing provider dispatch, exactly one company
  -> actual source/provider admission + durable frozen inventory
  -> existing business rules through a pure selected-company planner
  -> existing exact local chunk application + atomic publication holds
  -> LOCAL_VERIFIED_HELD
  -> separately gated exact publication + fresh remote readback
  -> SYNC_CONFIRMED
```

This is a new orchestration boundary inside the existing Python coordinator, not a new scheduler, autonomous framework, inference lane, or parallel writer.

Normal `run_start` is unsuitable unchanged: it can start global synchronization, manage review export, purge reviews, process pending Company events, clean closed jobs, and sync manual Opportunities **before** selection (`runner.py:692-760`). `defer_sync` suppresses only part of this. `requested_scan` calls ordinary cycle creation/synchronization and renames the shared request (`scan_request.py:55-85`). Do not route exceptional work through them.

However, the historical feasibility amendment overstates why reuse is impossible. `Engine._commit` delegates to its repository (`engine.py:213-216`); `SQLiteRepository.commit` is local (`sqlite_repository.py:502-567`). `_sync_cycle` is likewise backend-dependent. They are not intrinsically Google writes. The actual concerns are shared lifecycle mutations, dirty-data eligibility, and generic reconciliation—not the names “commit” or “sync.”

The existing pure-planning seam is `exact_cycle_planner._freeze` (`520-566`), using `PlanningRepository` and `PendingState`. Expose a supported, explicit interface around that seam. Do not call the outer `freeze_exact_cycle_plans` wrapper unchanged: it assumes ordinary cycles/inbox and current remote controls (`569-674`).

Two reuse traps must be addressed:

- `_normalize_history_guards` (`455-473`) narrows the engine's full expected source/review/decision guards. Retained local planning must keep full guards, as the local branch of `LocalPipeline.stage` already does (`278-284`). Do not weaken them to make reuse tests pass.
- `_finish_company` writes ordinary `Active Cycle ID`/Scan State metadata (`engine.py:1093-1102`). Extract a finalization policy; preserve job semantics without asserting ordinary lifecycle ownership. Also preserve authoritative managed-review claim checks: `_stage_posting` consults review runtime through `state.path` (`921-927`); an in-memory State must not silently remove that protection.

## 4. Dependency and ownership map

Paths below are relative to production `/home/chris/job-search-helper_old`, unless marked feature/new. Owners describe proposed development lanes, not authority to edit during this review.

| Component / file | Reuse, isolate, or bypass | Required boundary | Proposed owner |
|---|---|---|---|
| `company_events.py` canonical fact/source revision | Reuse | Current unique Company; stable source/provider identity; active/unclaimed | Intake lane |
| `scan_request.py` parsing/fingerprint | Reuse and narrow extension | Exactly one Company; explicit bridge/operator/repair origin; no mixed provenance | Intake lane |
| `scan_request.requested_scan` | Bypass | No ordinary cycle creation or shared request consumption | Intake lane |
| Existing ATS/provider dispatcher and inventory conversion | Reuse | Only admitted Company; complete descriptions; one durable fetch result | Intake lane |
| Ordinary browser fallback/progress | Isolate | No normal progress writes before admission; initially hold unsupported routes | Intake lane |
| Feature `retained_work_exception.py` | Retain, repair, rebase | Immutable admission and historical manifest; no settlement/publication authority | Intake lane |
| Feature `retained_work_runner.py` | Redesign orchestration | Dedicated session journal; no ordinary State/inbox registration | Intake lane |
| `batching.py` PlanningRepository/PendingState | Reuse | Pure snapshot planning; no flush to authoritative State | Coordinator/storage lane |
| `engine.py` posting/absence logic | Reuse via small pure-planner API | Full guards, read-only claim checks, explicit finalization policy | Coordinator/storage lane |
| `exact_cycle_planner.py` inner planner and sealed plan | Extract/extend | Explicit purpose/admission binding; no ordinary outer wrapper | Coordinator/storage lane |
| `exact_local_plan.py`, `sqlite_repository.py` | Reuse/extend | Atomic mutation + APPLIED journal + per-record delivery ownership | Coordinator/storage lane |
| `inbox.py` | Isolate exceptional inventory | Prefer separate namespace/store outside ordinary discovery; reject foreign-purpose imports | Coordinator/storage lane |
| `runner.py`, `local_pipeline.py`, `scrape_first_pass.py` generic paths | Bypass and defend | Reject exceptional ownership before consumption/reconciliation/remote setup | Coordinator/storage lane |
| `sheets_sync.py`, `run_sync.py`, other publisher entrypoints | Enforce exclusion | No global dirty discovery may publish held rows; selected publisher uses canonical durable plan | Coordinator/storage lane |
| `publication_receipts.py`, exact remote intent/ack primitives | Reuse later | Local phase cannot mint confirmed receipt; exact fresh remote readback required | Coordinator/storage lane |
| `exact_cycle_sync.py` ordinary wrapper | Bypass initially | Separate retained-purpose orchestrator; do not fabricate normal cycle evidence | Coordinator/storage lane |
| Company bridge processing, closed-job cleanup, manual Opportunities sync, review lifecycle, terminal outcome/release hooks | Bypass | No global lifecycle effects in local exception | Intake lane routes; QA verifies |
| Negative, race, crash, compatibility, installed/deployed tests | Independent verification | QA owns tests/report only; implementation owners repair their own files | QA lane |

Only one lane edits a given production file at a time. Cross-cutting API contracts are agreed before parallel edits; the coordinator reconciles narrow diffs against production. MuleLab owns coordination, retrieval, tests, storage, and backups. Jetson retains exactly one inference lane; this bridge requires no new Jetson capability.

## 5. Durable state and no-side-effect contract

Use one authoritative intake aggregate, not a second queue and a receipt for each step:

`REQUESTED -> RESERVED -> INVENTORY_FROZEN -> PLAN_FROZEN -> LOCAL_APPLYING -> LOCAL_VERIFIED_HELD -> RELEASE_READY -> SYNC_PENDING -> SYNC_CONFIRMED`.

`HELD`, `CANCELLED`, and recovery-required outcomes retain the prior durable phase and evidence; they do not rewind it. Existing APPLIED/VERIFIED chunk journals remain authoritative for local effects. Public publication receipts keep their existing `LOCAL_COMMITTED -> SYNC_PENDING -> SYNC_CONFIRMED` semantics. `RELEASE_READY` here means selected data-publication eligibility, not automatic code release.

`RESERVED` grants provisional scheduling ownership after basic authorization and known-Company checks; it does not approve an as-yet-unresolved provider identity or permit job mutation. Actual source containment and immutable admission binding must pass before `INVENTORY_FROZEN`. Seal those once-known fields rather than rewriting an already-admitted identity. This separates the necessary prefetch from authority to apply its result.

Persist at least request ID/origin/digest, Company ID and canonical fact/source revision, destination and database identity, policy/schema version, historical-manifest and authorization/admission references, reservation owner/generation, frozen inventory identity/content digest, plan/code/config/dependency identity, local apply ID/cursor, and publication/ack references when applicable. Freeze authority-bearing payloads; reject unknown schema/state and changed request-ID reuse. Query by exact request; completed sessions remain audit history and do not prevent a second sequential request.

Keep exceptional session/inventory records outside ordinary State/inbox discovery. Merely setting `blocked` or adding a metadata flag is not enough because generic code can unblock/reconcile it. If shared tables are selected instead, every enumerator, mutator, cleanup, resume, and publisher must enforce purpose ownership first; this is a larger proof surface than a separate inventory namespace.

| Phase | Allowed effects | Forbidden effects |
|---|---|---|
| This review | Read-only source/local evidence; disposable tests; this report | All production mutations and external calls listed in the request |
| Pre-admission validation | Read local authority and exact request; verify existing authorization; bounded lock ownership in a future implementation | Google construction/auth; provider fetch before valid basic authorization; schema creation as a side effect of a read |
| Reserved preflight | Request-owned journal writes; exactly one supported Company provider fetch | Broad scan, ordinary browser progress, bridge-wide delivery, old-cycle mutation |
| Plan/local apply | Frozen inventory read; pure planning; exact local chunks and atomic held-delivery provenance | Google client, remote read/write, global sync, ordinary cycle/review lifecycle, automatic repair/release |
| Explicit publication stage | Only selected frozen projection; fresh Google guards and readback after its gate | Global dirty sweep, foreign/historical work, automatic backlog processing |

No-Google local work cannot simultaneously prove current remote workbook state. Record snapshot freshness/version honestly; fail local admission when required local controls are missing or stale under a defined policy. Recheck remote Company/job controls at the separate publication gate. Do not describe cached `Scan Cycles` rows as a live workbook check, or relax remote publication guards because local work already completed.

### Ownership, dirty provenance, and concurrency

Before the first shared-record mutation, install a durable hold visible to every publisher. Store it in the **same jobs-database transaction** as the mutation and existing APPLIED chunk record. Bind exact stable record identity, Company/source/request/plan/chunk, fields owned, expected before values, written values/digests, and prior dirty baseline. Preserve unrelated dirty fields and manual edits; ambiguous shared ownership holds the operation.

Publishers must exclude held rows before discovery/claim, and recheck under their write/claim boundary so a plan cached before the hold cannot escape it. A held field may force holding its whole row if the existing publisher cannot safely separate fields. Every local writer must reject or safely version a conflicting mutation. Release/ack authority must come from the durable exact intent—not caller-supplied row numbers, mutable metadata, or the mere absence of a legacy marker.

Define one lock acquisition order for intake, local writer, publisher, and release/start paths after auditing existing nesting; test that order. Do not hold unrelated database transactions across provider network calls. Reserve first, fetch outside the short mutation transaction, and compare fresh guards/generation when sealing or applying. Process/PID liveness alone is not ownership proof; never remove a lock to recover.

The historical manifest stays frozen. Account for new work with an exact allowed-delta/ownership ledger; do not silently rebaseline historical records. If current policy requires an empty dirty baseline, refuse when it is nonempty. After new writes, partition dirty data against that original baseline and exact owned deltas rather than requiring permanent global emptiness.

### Crash/restart rules

- Before a provisional reservation commits: no accepted work. After it commits: identical request retries find the same reservation; another owner/generation cannot take it over silently. Full source/provider admission is sealed only after the fetched identity passes containment; provisional ownership alone never authorizes job application.
- A fetch is not durable until its frozen payload is committed. If the process dies between provider response and freeze, report interrupted/unknown preflight; do not promise impossible exactly-once network retrieval. Policy may explicitly allow a new read-only fetch before durable freeze, or hold for retry. After `INVENTORY_FROZEN`, never refetch to resume.
- Plan once from frozen inputs; after any local/remote effect, never silently regenerate a successor plan. Changed guards produce a hold with evidence.
- Local mutation and APPLIED record commit together. If a mirror/checkpoint update is lost, read the authoritative journal, verify, and repair only the owned mirror—not replay the chunk.
- Cross-file reservation, request-consumption, and inventory writes are not one transaction. Use stable keys, durable checkpoints/readback, and compare-before-rename; never overwrite a different last-request record. Prefer a dedicated request namespace to avoid that shared-file coupling.
- Lost remote response remains `SYNC_PENDING`/uncertain. Reconcile the exact durable intent with authenticated fresh readback before any permitted retry. Never clear dirty data, refetch jobs, or release ownership merely because transport failed.
- Cancellation, source/status/review changes, full disk, expired authorization, foreign process ownership, and schema mismatch hold before new effects. If a chunk already committed, report and preserve it; do not claim rollback or undo user edits.

## 6. Exact narrow repair for the reported preflight QA finding

For the unavailable later reservation-bound journal, the required invariant is:

**The source/provider identity derived from the returned frozen inventory must equal the identity sealed in the independently validated immutable admission—not merely agree with hashes stored alongside that inventory.**

Repair the journal's authoritative readback/validation function (and reuse it for fresh consume and cold recovery), rather than adding a second confirmation token:

1. Load the durable admission by exact reservation ID from its authority store. Validate its schema, state, payload digest, authorization references, destination, Company, request, source revision, and reservation binding. Do not trust a caller's copy as authority.
2. Load the frozen-preflight row. Require its correct frozen state and supported schema; recompute its full payload/content digest; validate all journal cross-links to the durable admission.
3. Canonically derive the same Company/source/provider identity used during admission from the trusted Company snapshot and frozen inventory, including actual source URL/ATS/provider-board identity. Compare the complete identity digest against the admission's sealed identity digest. Re-run containment checks where canonicalization/policy versions require it.
4. Preserve a separate full-inventory digest so changes to jobs/descriptions cannot pass merely because the source matches. Reject malformed inventory, unsupported status, cross-company/destination/request substitution, unknown states, or partial records before exposing a fetcher or constructing writers.
5. Perform the current-control/generation comparison under the shared ownership transition; use a fresh clock for authorization decisions. A read-only audit of an expired record is different from authority to continue mutation.

In the recovered implementation the concrete missing comparison belongs in `_validate_prepared` after `validate_frozen_admission`: recompute the canonical digest of `_admission_company(current, company, prepared.inventory)` and compare with `repeated['reservation_payload']['company_identity_digest']`. Use the admission function's exact field selection/canonicalization; validate inventory schema first. Both commit and recovery already call this function, so the repair can stay narrow. It does **not** repair F-B, F-C, or F-D.

Required proving test: alter every relevant mutable preflight row and recompute all its self-hashes while leaving the immutable admission untouched; fresh consume and cold readback must refuse before any writer/provider reuse. Include aliases, changed ATS with unchanged URL, changed source with unchanged ATS, and another Company's identity.

Threat-model limit: hashes detect inconsistency, not a malicious operating-system owner who can rewrite every authority and signing key. Existing signed retained-work authorization must remain verified; do not present a Python private token, a frozen dataclass, mode 0600, or a same-row hash as a new security boundary. Do not invent a new signing service for ordinary operator requests unless a distinct trust boundary actually requires it.

## 7. Minimum implementation order and file-level scope

These are recommendations for a later implementation turn, not actions performed or newly authorized here.

| Phase | Smallest deliverable and file scope | Exit gate |
|---|---|---|
| 0. Re-establish a reproducible baseline | Recover/identify the exact missing candidate and designs; reconcile restart card/evidence index; pin current production hashes and protected overlay. Documentation only. | Reviewer can identify exactly what is being proposed; no stale-tree replacement. |
| 1. Repair admission and freeze | Feature `retained_work_exception.py`, `retained_work_runner.py`, their tests; optionally narrowly extend `scan_request.py` provenance validation. | F-A repros fail safely; schema/current-control tests pass; isolated journal never creates ordinary cycles/inventories. |
| 2. Expose normal planning | `exact_cycle_planner.py`, small `engine.py` seam/finalization policy, targeted planner/engine tests. Reuse `batching.py`. | Normal-vs-selected semantic equivalence; full source/review/manual guards and claim checks preserved; zero external/lifecycle effects. |
| 3. Install delivery ownership barriers | `sqlite_repository.py`, `sheets_sync.py`, relevant `run_sync.py`/publisher guards; `inbox.py`, `local_pipeline.py`, `runner.py`, `scrape_first_pass.py` only where consumers need explicit refusal. | Generic start/resume/sync/reconcile/cleanup cannot consume or publish held work, including precomputed publisher plans. Required before phase 4 shared writes. |
| 4. Connect one local vertical slice | `exact_local_plan.py` retained-purpose validation/atomic hold; dedicated runner/session store; targeted integration tests. | One synthetic Company fetches, filters, durably saves, and restarts without replay; unrelated and retained data unchanged. Two sequential requests work without deleting history. |
| 5. Add selected publication | Reuse `sheets_sync.py` exact intent/readback/ack and `publication_receipts.py`; adapt a narrow publisher boundary instead of invoking ordinary `exact_cycle_sync` wholesale. | Fresh remote controls, exact identities, lost-ACK recovery, foreign dirty protection, no fabricated confirmation. Local staging alone is not M1. |
| 6. Resolve M1 request eligibility | Separate operator provenance in `scan_request.py`/admission; if required, reviewed queued-unstarted reservation enforcement in old and new scheduler paths. | Samtec eligible under an explicit policy, or honestly blocked; no historical mutation or fake bridge event. |
| 7. Guarded integration and acceptance | Narrow protected patch, scoped rollback manifest, installed-source tests; bounded pilot and independent deployed QA; later authorized sanitized backup. | Roadmap acceptance evidence, not source-test counts, controls enablement. Broad backlog/unqualified auto-release stay disabled. |

Phase 6 design should be decided early so phases 1-5 do not implement an unusable pilot, but its live activation must wait for the earlier safety gates. Phases 2 and 3 can proceed in parallel after agreeing the authority/plan interfaces; one owner per file. No need to repair the entire historical backlog before finishing useful design and isolated testing.

Keep the pure planner and narrow runner small. Avoid a new provider framework, copied filters, duplicate receipt state machine, second coordinator, or a generalized workflow engine. The substantial work is enforcing ownership across existing consumers, not adding more orchestration objects.

## 8. Can Milestone 1 use this exception? No, not unchanged.

The bridge-only path can demonstrate a disjoint newly added Company event. It cannot truthfully serve an operator-created Samtec pilot: Samtec lacks that event provenance and is already in historical membership.

Two safe options:

1. Preserve the current outside-only policy. Samtec waits until its historical admission barrier is legitimately resolved. A disjoint Company pilot supplies partial evidence but does not silently replace the roadmap's Samtec requirement.
2. Define a separate **queued-but-unstarted historical member** policy. Current Samtec evidence makes this worth assessing, but does not yet prove it safe. The policy must prove absence of owned inventory, plan, application, receipt, remote intent, claim, dirty mutation, and foreign/shared job overlap; reserve the Company/source against both old and new schedulers; and make ordinary old-cycle resume respect that reservation without altering the old cycle record. Specify later reservation retirement so historical work cannot concurrently or accidentally replay the same intent. Do not auto-skip or settle the historical member.

Minimum separate operator-request provenance:

- Distinct schema/version and request ID namespace, created through the authorized local operator/coordinator path; origin is explicit and immutable, mutually exclusive with bridge-event and repair-retry provenance.
- Exactly one stable Company ID, immutable enqueue time, canonical Company/source revision and destination; no authority derived solely from a name, URL, row number, or arbitrary JSON flag.
- Bounded purpose/capabilities: one company intake, specified historical-admission policy, no retained-work settlement, no global scan, publication separately gated.
- Durable request digest, retained-manifest reference, policy version, code/config/dependency identity, and reservation owner/generation. Refuse changed reuse.
- Current source/status/claim/cancellation checks at admission, before local mutation, and before publication; authoritative request creation/ownership evidence retained.

The existing parser already supports manual company-only requests (`scan_request.py:93-175`); extend its provenance deliberately, not by creating a fake `company_event`. Operator provenance authorizes the origin of the request; it does not override membership or source conflicts.

Samtec M1 completion still requires today's normal dispatcher result and full-description/filtering behavior, duplicate/manual protection, durable normal storage, exact Sheets synchronization/readback, lost-ACK recovery without refetch, and idle/busy intake timing evidence. No historical job count is an expected result. Record counts and reasons from the actual bounded pilot.

## 9. Required test matrix and independent-QA gates

| Area | Required negative/positive cases | Required evidence |
|---|---|---|
| Admission | Authentic bridge/operator separately; mixed/fabricated/stale provenance; expired authorization; membership/provider aliases; another unfinished blocker | Refusal before provider/writer; exact admitted binding on success |
| Frozen readback | In-memory mutation; complete stored-row tampering with recomputed self-hashes; wrong state/schema/request/company/destination/source/provider | Admission remains untouched; every tampered case refuses on fresh and cold readback |
| Control races | Pause/inactivate/delete/source change/claim/cancel between every read and commit; competing reservation; generation takeover | Shared transition/fencing prevents new unauthorized effects; committed prior work honestly retained |
| No-side-effects | Make Google/auth/global sync/ordinary start-cycle/review lifecycle/bridge delivery/manual sync/outcome/release constructors fail if invoked | Zero calls in all local success/failure/restart branches |
| Lifecycle isolation | Generic start/resume/full/sync/named sync/reconcile/ack/cleanup/first-pass against held session | Held session invisible or explicitly rejected; cannot strip marker and fall into legacy confirmation |
| Business equivalence | Titles, locations, full descriptions, duplicates, stable job keys, manual choices, review claims, estimate salary fallback when posting pay blank, real posted pay precedence | Same qualified outcomes as normal rules; estimate is not misrepresented as advertised salary; user estimate preserved |
| Inventory quality | Complete/partial/empty/access-denied/unsupported/malformed inventory; missing description; query/provider alias | No false absence closure/full success; deterministic hold or qualified result |
| Local commit | Before/after each chunk, commit before mirror, retry twice, changed guarded fields, readback mismatch | Atomic APPLIED + hold; no replay; exact local verification |
| Dirty ownership | Foreign pre-existing dirty fields; same row shared by two owners; changed manual fields; generic publisher before/after hold and with cached plan | No held or foreign publication; no clearing another request's dirty fields |
| Exact publication | Lost response before/after remote effect; reordered/inserted rows; mismatched destination; altered caller row metadata; legacy cleanup; duplicate confirm | Durable exact intent + fresh readback; pending until verified; no forged SYNC_CONFIRMED |
| Crash/resource bounds | Reserve/fetch/freeze/plan/apply/request-consume/readback/ack boundaries; full disk; corrupted/missing mirror; shutdown/restart | Recover same immutable work or hold; never refetch after freeze; no false completion |
| Sequential lifecycle | Two independent completed requests; a held request followed by allowed disjoint work | No “exactly one journal row” assumption; no history deletion; explicit ownership release |
| Historical preservation | Snapshot old cycle, inventories, plans/cursors, journals, receipts and protected source/control records | Exact before/after equality; Saronic conflict remains held |
| Deployment | Installed hash match, protected behavioral regression, rollback exercise, local isolation proof, then bounded real pilot | Fresh independent deployed QA; source-only PASS is insufficient |

Suggested test files: extend current retained-work, exact-local-plan, exact-cycle-planner/sync, durable-inbox, SQLite, publication-receipts, runner-cycle/fresh-request, local-pipeline and first-pass tests; add one end-to-end isolated-company test suite. Do not multiply largely overlapping test harnesses.

Independent gates:

1. **Source gate:** original failure reproductions fail safely, normal-regression tests pass, reviewer accepts exact diff/hash and ownership contract. Tests must exercise public entrypoints and tampered recovery, not only private happy-path helpers.
2. **Installation gate:** reviewed narrow patch matches installed hashes; pre-existing work preserved; exact rollback available; generic paths refuse owned work; no live pilot yet.
3. **Local operational gate:** bounded selected-company proof leaves retained/unrelated data unchanged and held local work cannot escape through ordinary paths.
4. **Publication gate:** separately qualified selected synchronization and fresh readback, lost-ACK proof, no foreign dirty clearing; only then M1 publication is proven.
5. **Roadmap/final gate:** M2 event/restart dedup and timing, M3 classification, M4 one-lane bounded coordinator repair, M5 complete-release activation/retry/rollback, M6 at least three distinct unfinished structures plus shared-adapter regression and exception scenarios. Final independent deployed QA, F1-F8 reconciliation, and verified scoped GitHub backup remain required.

QA failure produces a new immutable failure report, repair assignment, and fresh verification. Do not weaken guards or redefine completion. Existing milestone percentages are not substantiated by this review; use an evidence checklist rather than extrapolating test counts into completion or an ETA.

## 10. Explicit do-not-do list

- Do not mark, supersede, advance, reconcile, remove membership from, or auto-settle `CYC-B639C6D864EC`; do not resolve Saronic by choosing whichever salary/source value makes a test pass.
- Do not turn Samtec into a fake bridge event or treat queued membership as absent membership.
- Do not use normal `start`, resume, pipeline, exact-sync, or first-pass wrappers as an exception shortcut without enforced ownership boundaries.
- Do not create a Google client, authenticate, fetch remote controls, write remotely, or run global synchronization in local-only phases.
- Do not assume deferred sync prevents a different publisher from seeing shared dirty data.
- Do not put ordinary unblocked inbox inventory behind an advisory exception flag.
- Do not accept caller-controlled row metadata for confirmation/dirty clearing or let cleanup erase the protection against legacy reconciliation.
- Do not refetch frozen work after a lost acknowledgement; do not silently replan partially applied or published work.
- Do not remove locks, trust stale PID text, start duplicate owners, or add a second Jetson inference lane.
- Do not erase user-entered salary estimates or mislabel them as posted pay. Preserve the estimate when posting pay is blank; real posted pay may take precedence for evaluation only under the defined field/provenance policy. Preserve manual decisions, Opportunities, unrelated changes, private data, and existing history.
- Do not restore the entire stale feature checkout over production or introduce a second filtering/coordinator framework.
- Do not enable broad backlog, unqualified automatic code release, or claim M1/the project complete from local inventory freezing.
- Do not commit secrets, databases, raw job data, private backups, or this session log to GitHub. No GitHub write is authorized by this review request.

## 11. Continue or discard?

**Continue useful components; reject and replace the recovered runner's integration boundary.** Keep the historical manifest/admission and exact immutable-journal work as source-only inputs, subject to the repairs and tests above. Do not invest further in its ordinary State/inbox handoff. Recover the later candidate before claiming its exact QA finding is fixed; if unavailable, reimplement only that small readback invariant against the pinned current baseline, with the recorded failing case.

Next coordinator action after review: establish the missing artifact/version baseline and approve the narrow interface/ownership plan, then assign non-overlapping intake, storage/publication, and QA lanes. Do not resume a live run merely because this report exists.

At the next authorized documentation checkpoint, replace the long card's opening status with one compact current snapshot: paused/rejected status, candidate/release hashes, milestone evidence states, exact remaining blockers, worker ownership, goal reference, next action, and links to an append-only history. Reconcile stale QA-ledger entries against newer evidence; do not delete the original findings. This review deliberately did not edit the restart card.

## 12. Source fingerprint record

The following SHA-256 values identify inspected content, independent of dirty-tree HEAD. Paths prefixed `src/` below are under `/home/chris/job-search-helper_old`; `feature/` means `/tmp/job-search-helper-integration-automation`.

```text
5fe9d31e045ad760eb825582ed427c05169aadce9c83047e68e9220b8a4f01e8 src/job_search_helper/runner.py
7a3f8e1784f73fb0d56f4e3fde68e60916c5b2b71e60122400bc501e58a281cc src/job_search_helper/scan_request.py
73e5c8036ca28db8d4ebdb767715c09c62271b0284cb8ef46ecd0e36b6c561fe src/job_search_helper/engine.py
3b9680a8f01868aea3d77cd9e8add958795dccec0e2fe7a8e247d5a0fe240b2d src/job_search_helper/local_pipeline.py
e56a7d30857f0cf29b169a00ad762f0feeda800ddf9c0031ade025ab238d1f44 src/job_search_helper/inbox.py
22a4aa8d6069f3bca4e8d852f677ddf8eb1993415ead4006fe530d46f5179594 src/job_search_helper/sqlite_repository.py
e57ab1bc4a603b512425e4626803fe27068d790dfeff68529a98f614caa82fae src/job_search_helper/publication_receipts.py
9b7709a83754b2eb49322bc76b1e921d7a3e0aba598dd4b56fb7f2cd18a3ca94 src/job_search_helper/scrape_first_pass.py
f9b6a74889253de468c52be8a46649886e1b713dab6a81cb699f3e76badef298 src/job_search_helper/exact_cycle_planner.py
07bd46a42f2f0b25b7023d592e358e10a3d4c56a9381cc8903a91540245199ff src/job_search_helper/exact_local_plan.py
0d6360f514f188a510ec6c36d09dc47d9150f97d6bab292910bcc11e8ea52efb src/job_search_helper/sheets_sync.py
fcae28a4b13dc3d6ce6723d2d494e4e4d440ca53bbb884064b5172b8bc76620a feature/src/job_search_helper/retained_work_exception.py
803fdda2550ed75ce3613b6be77020ce678a635e9d5b9c5083bc8462e034027d feature/src/job_search_helper/retained_work_runner.py
f955c11cc1617484b3a918f0566f26303388b1cbfa200822156d9d4bb2f68d13 feature/temp/integration-coordinator/COORDINATOR_STATUS.md
```

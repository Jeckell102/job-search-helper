# Historical blocker architecture decision — 2026-11-19

## Decision

Choose **C: a narrowly productionized retained-work exception for each new,
non-overlapping Company event**, after one separately reviewed and signed
authorization for the historical blocker `CYC-B639C6D864EC`.

This is the smallest safe path to resume automatic new-Company intake while
preserving the historical work. It is not a general bypass of an unfinished
cycle: each request remains event-, Company-, revision-, and manifest-bound;
only a Company disjoint from the historical cycle is eligible; it uses a
separate durable reservation and exact publisher; and normal start remains
held while the reservation exists. A terminal-hold pause remains the strategic
route back to ordinary scheduling, but is not presently deployable. Full
reconciliation is also the correct long-term outcome, but cannot be made a
precondition for ordinary new-Company intake without materially delaying it.

## Fresh evidence and source-divergence boundary

The read-only status for `CYC-B639C6D864EC` reports 45 saved inventories,
6 legacy plans, and two confirmed receipts (the earlier broader count is 47
inventories / 8 plans). Its state is still
`SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED`; it must not be superseded,
silently paused, or broadly resumed for a one-Company request.

The protected source at `/home/chris/job-search-helper_old` is authoritative
for any future deployment and differs from the overlay. In particular, its
dirty `runner.py` already contains `queue-company`,
`retained-exception-preview`, `recover-interrupted-cycle-status`, and legacy
migration preview/adoption CLI wiring, plus normal-start invocation of
`CompanyEventBridge.process_pending()`. The overlay's `runner.py` lacks that
interface and has a different general scan/FIRST-PASS flow. No overlay result
is deployment proof, and protected files must not be copied over or replaced.

## Why the other choices are not the near-term production route

### A. Reconcile all retained work first — correct but not minimum unblock

Existing legacy plans are neither remote publication plans nor adequate exact
receipts. `sync_plans.cursor` is local application progress. The production
preflight establishes that all eight inspected plans are legacy three-key
payloads with nonzero local cursors and no exact seal/receipt. Direct Google
replay would confuse local and remote acknowledgement.

The current selected legacy migration is incomplete for the needed set:
its Davidson path handles completed cursor evidence, while a partial plan such
as 67/208 requires the planned cursor-aware prefix/suffix conversion. Further,
the current adoption command accepts an approval JSON whose binding can be
freshly recomputed; independent QA held it because signer/reviewer provenance
is not verified. Therefore A requires signed-provenance enforcement, per-plan
conversion/recovery, and verified publication for every saved item. It should
continue as background recovery work, not gate new disjoint Companies.

### B. Signed terminal-hold pause — not deployment-ready

The exact-pause modules have useful primitives:

- `exact_recovery_pause.freeze_exact_pause_journal()` freezes immutable scope.
- `PauseApplyStore` journals intent and confirmation order.
- `execute_exact_recovery_pause()` has chunk/readback/state/cycle finalization
  semantics under the normal scraper lock.

But the currently wired `runner.pause_interrupted_cycle()` starts the global
`run_scoped_sync` before and after the pause, which violates exact-only
containment. Its live profile is `compact-v1`, where claimed/token/scan fields
are local-only and the current pause executor requests remote fields that do
not exist. It also assumes an existing remote Scan Cycles row although the
fresh preflight found zero remote rows. Finally, terminal manual holds lack
the exact confirmation required by the terminal-hold manifest. B therefore
cannot safely be activated by simply signing a reason or calling the existing
command.

## Existing sufficient retained-path primitives

Once a reviewed manifest is activated, these components collectively provide
the required safety model:

1. `CompanyEventBridge` consumes the local Company outbox under the normal
   scraper lock, atomically writes an event-bound `next-scan.json`, records a
   receipt, and handles latest-revision coalescing/cancellation.
2. `retained_work_exception.admit_disjoint_company_request()` verifies the
   active signed historical manifest, bridge receipt, exact Company revision,
   no claim, one Company-only scope, no historical Company/source/provider
   overlap, and that the sole blocker remains the authorized historical cycle.
   Its durable reservation is idempotent by request/event and rejects reuse.
3. `retained_work_runner.prepare_exceptional_start()` and
   `commit_exceptional_start()` bind the immutable inventory, company snapshot,
   event, source revision, historical-cycle digest, and admission into a
   durable start journal; the normal lifecycle guard prevents a normal runner
   from racing it.
4. `run_retained_reservation()` plans and applies exactly the selected Company
   locally, then uses `RetainedSessionStore` and
   `retained_work_publication` for pre-dispatch chunk claims, exact readback,
   selected-local acknowledgement, settlement, and reservation-scoped FIRST
   PASS release. This is deliberately not the Inbox/global synchronizer path.

This covers one safe *execution* route. It does not create a production call
graph from the event bridge to the route.

## Missing production call graph

No current protected CLI command invokes the complete retained pipeline.
`retained-exception-preview` only builds signer claims; `queue-company` only
creates an operator request; the normal runner's bridge only writes the
Company-event request. There is no approved command/service that:

1. reads one bridge-owned pending request and its receipt;
2. loads the active signed exception manifest and verifies its provenance;
3. constructs read-only State/local repository and the exact fetcher;
4. calls disjoint admission, fetches the one inventory, freezes/recoveries the
   retained start, and calls `run_retained_reservation()`;
5. reports the distinct states: event received, reservation frozen, local
   committed, Sheets confirmed, FIRST PASS released, or held;
6. removes/settles only the exact bridge request after the retained settlement.

Do not add that behavior to generic `start`, `sync`, or a global watcher.
Add a dedicated, normal-lock-owned `run-retained-company-event` service/CLI
with no fallback to normal cycles, Inbox, global `run_scoped_sync`, broad
review, cleanup, outcome processing, or another Company. A controlled runner
may invoke it automatically only after the manifest has already been signed,
activated, and independently accepted. Until then, event receipt status must
be `WAITING_FOR_RETAINED_AUTHORIZATION`, not silently retried as a normal run.

## Required implementation constraints

- Keep the Company event outbox and `CompanyEventBridge` as intake authority;
  never bypass it with a raw request file.
- One active retained reservation only; preserve current lock order: normal
  scraper lock, then retained-publication lock. Never hold SQLite transactions
  across network operations.
- Build factories only after the lifecycle hold/preflight succeeds; protect
  normal State/Inbox from construction and mutation on every retained path.
- Require verified signer/key identity and expiry for the authorization
  envelope, not merely a matching JSON binding. Bind manifest digest, event,
  Company/source revision, release/configuration versions, and exact control
  snapshot.
- Re-read controls before local apply and each remote dispatch/readback. Any
  pause, claim, source/revision drift, provider/URL alias, blocker-set change,
  or profile drift is a held reservation, not a retry.
- Treat a timeout/lost response as readback-only. Settle only after exact
  remote acknowledgement and FIRST PASS release; never consume/replay a
  different event or use broad backlog processing as recovery.

## Acceptance tests before enabling C

1. Protected-source integration tests prove the event-bridge -> dedicated
   retained command call graph for an eligible disjoint Company. Assert zero
   normal State/Inbox/global-sync/broad-cycle mutation and exactly one Company
   fetched.
2. Crash matrix: before/after bridge request, admission reservation, inventory
   freeze, local apply, remote-intent claim, lost remote response, remote
   readback, selected-local acknowledgement, FIRST PASS release, and
   settlement. Restart must never duplicate fetch, local rows, remote writes,
   review release, or event acknowledgement.
3. Negative admissions: Company in blocker scope; same normalized name/URL or
   provider alias; duplicate/older event; changed revision; paused/claimed
   Company; multiple blockers; expired/bad signer authorization; missing or
   altered bridge receipt; and non-company-only request. Each produces no
   remote write and preserves saved historical work.
4. Compact profile test: local-only Company controls are fetched locally;
   remote reads/writes use only visible fields. Verify Job History and Job
   Evidence exact identities/readback plus FIRST PASS release; a failed guard
   leaves no receipt/dirty acknowledgement.
5. Concurrency tests: normal start rejected while retained start/reservation
   exists; retained command rejected while normal lock/lifecycle owns work;
   second Company event is held, not co-run.
6. Fresh guarded live demonstration of one eligible disjoint Company:
   event receipt -> scoped fetch -> durable storage -> exact Sheets status ->
   managed FIRST PASS terminal result. Historical saved counts must be
   byte-for-byte unchanged except dedicated retained journals/receipts.

## Recommendation to the coordinator

Implement and independently review the dedicated retained-event orchestrator
on the *current protected source reconciliation branch*, not the overlay.
Keep A's signed legacy migration and B's compact-compatible terminal-hold
adapter as separate tracks. C is a temporary containment bridge, not evidence
that `CYC-B639C6D864EC` is complete or safely paused. Its authorization must
be time-bounded and removable once B or complete A returns the system to the
ordinary Company-only lifecycle.

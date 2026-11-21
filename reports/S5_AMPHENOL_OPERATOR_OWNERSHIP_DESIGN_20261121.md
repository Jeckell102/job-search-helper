# Operator-selected Amphenol observation: smallest safe follow-up

## Decision

There is **no existing route that satisfies all four requirements**: (1) a
genuine operator-selected request, (2) normal one-company scrape, (3) typed
AcquireTM partial recognition, and (4) automatic queueing of the reviewed
wrapper.  Two deliberately separate routes already exist:

* `queue-company --company-id COMP-0490 --request-id <stable-id>` persists an
  `operator-company-scan-request-v1`, with exactly one Company and current
  source revision.  It performs no fetch, cycle creation, Company mutation, or
  replacement of another pending request.  Normal `start` admits it through
  the ordinary company-only path.
* `AmphenolRecipeEnrollment` can queue one isolated reviewed wrapper
  (`RECIPE_PILOT_QUEUED`), but it accepts only an actual
  `company-event:<CEV-...>` identity and only an
  `ordinary-company-event-settlement-v1` qualified partial.

Using the second route by creating a synthetic Company event would falsify
provenance.  Using the first route unchanged cannot produce the qualified
outcome: `scrape_outcome_producer._ordinary_normal_cycle` expressly excludes
`operator_request` and the existing enrollment rejects it.  The requested
follow-up therefore needs one new, explicit operator-origin bridge; it must
not widen either generic path.

## Reuse without broadening

Reuse these existing boundaries unchanged:

1. **Request and admission:** `queue-company`, `operator_company_request`,
   `scan_request._operator_request`, normal company-only admission, and the
   existing request fingerprint.  The accepted request is exactly one current
   `COMP-0490` request with a new stable request ID and its frozen
   source-revision; it contains no `company_event` field.
2. **Observation:** normal AcquireTM dispatch and the closed
   `acquiretm_updatepanel_premature_read` witness.  Accept only the existing
   zero-job partial shape: exact Amphenol board, AcquireTM, no pending browser
   URLs/discovery gap, unchanged source revision, and a valid typed
   pagination-regression envelope.  Any other partial stays an ordinary hold.
3. **Durability/delivery:** the existing `scrape_outcomes`, outcome delivery
   reservation/receipt tables, `repair-coordinator` consumer, and host
   control/owner locks.  Delivery remains receipt-backed and one-outcome only.
4. **Wrapper safety:** existing `prepare-held-repair` plus `pilot-start` and
   the host checks that queue/campaign/autopilot are disabled, no pilot or
   unresolved inference exists, and the result is one paused isolated
   review-mode task with `max_sessions=1`.

## Minimal delta

Add a dedicated `operator-selected-amphenol-observation-v1` settlement and
host enrollment branch.  Do not alter the default operator outcome producer,
Company-event bridge, generic delivery drain, or release activation path.

### Application-side owner

Introduce one narrow settlement entry (new module/command is preferable to
loosening `ordinary_event_settlement`): it reads the *saved normal cycle* and
frozen operator request, then accepts only all of:

* `operator_request` is exactly `operator-company-scan-request-v1`, with the
  same request ID, sole Company `COMP-0490`, and 64-hex current revision;
* the saved cycle is company-only, has exactly that request fingerprint and
  Company, is terminal/owned by the request, and has no Company event, retry,
  retained, recovery, or broad `all` scope;
* the retained normal checkpoint is the existing valid typed AcquireTM partial
  witness, with no jobs or publication evidence; and
* fresh Company readback remains the same eligible Amphenol source and there
  is exactly one matching normal-cycle/mirror/outcome slot.

Its immutable binding should contain:

`{schema, request_id, company_id, source_revision, cycle_id,
request_fingerprint, runtime_binding_sha256, observation_sha256,
provider_inventory_sha256, authority:"operator-selected-amphenol-v1"}`.

The settlement may record one `QUALIFIED_INTEGRATION_REPAIR /
upsert_qualified_repair / pagination_regression` outcome with that explicit
operator authority, persist its local receipt before checkpointing terminal
state, and create no Company event/outbox item.  It must never publish to
Sheets, create a retry, install/release code, or start inference.  An already
matching receipt is idempotent; every mismatch is a hold.

This is intentionally a new named owner rather than a one-line exception in
`_ordinary_normal_cycle`: the latter would make every operator request eligible
for generic outcome handling and erase the provenance separation.

### Host-side enrollment

Add a second, sibling enrollment parser/record, e.g.
`WRAPPER_AMPHENOL_OPERATOR_ENROLLMENT`, whose exact JSON is limited to
`{request_id, source_revision}` (the Company is a constant check, not an
operator-provided choice).  It must reject simultaneous event and operator
enrollments and all retry/release-activation settings.  Its matcher accepts
only the new authority/schema and identity set above; the current
`AmphenolRecipeEnrollment` remains byte-for-byte event-only.

The sibling catch-up uses the existing one-outcome delivery reservation and
existing held-repair/read-owned-choice-input flow, then calls the existing
prepare/pilot commands.  It returns `RECIPE_PILOT_QUEUED` only after the exact
new receipt is accepted and the isolated review pilot exists.  It may not
drain the outcome backlog or match another Company/request/revision.

## Required gates/tests

* Fresh preflight verifies retirement is complete, all old retained routes are
  inactive, exactly one eligible current Amphenol source exists, request slot
  is empty, and global scrape/pilot controls permit the single normal start.
* Positive disposable proof: queue one operator request, admit one normal
  cycle, inject the closed typed partial, settle exactly one outcome, deliver
  one receipt, and queue exactly one isolated review task.  Assert no Company
  event/outbox row, no Google writer/publication, no release/retry, no second
  worker, and no broad queue consumption.
* Negatives: fabricated/foreign event; missing or changed source revision;
  duplicate/multiple Company; nonzero jobs; untyped/foreign pagination
  failure; source/runtime/cycle/mirror drift; existing publication; duplicate
  outcome; conflicting enrollment; enabled queue/campaign/autopilot; active
  inference/pilot; crash after each durable step.  All must hold, not retry or
  substitute provenance.
* Independent QA must verify the event-only route is unchanged and the normal
  `queue-company` route still does not qualify arbitrary partials.

## Operational sequence after implementation and QA

1. Freshly create the one operator request and retain its receipt; do not
   fetch from the queuing command.
2. Start only the normal one-company request under normal admission.
3. If—and only if—the exact typed partial settles, start the already enrolled
   operator-specific host catch-up.  It can queue one review pilot; the pilot
   itself remains reviewed and no release is automatic.

This is a design only.  It authorizes neither a live request nor a source,
host, database, network, or deployment change.

## Evidence inspected

* approved after-image `candidate/src/job_search_helper/runner.py`:
  `queue-company` and operator request call;
* `scan_request.py`: exclusive one-company operator provenance contract;
* `scrape_outcome_producer.py`: operator requests intentionally excluded from
  generic normal outcomes;
* `ordinary_event_settlement.py`: closed typed witness/local-only settlement;
* `candidate/dev/wrapper-coder/tools/host_server.py`: event-only enrollment,
  exact outcome matching, and isolated pilot gates;
* coordinator reports `S5_AMPHENOL_POST_RETIREMENT_SMALLEST_REQUEST_20261121.md`,
  `S5_AMPHENOL_GENUINE_EVENT_OWNERSHIP_PATH_20261121.md`, and
  `S6_AMPHENOL_THIRD_STRUCTURE_INDEPENDENT_20261121.md`.

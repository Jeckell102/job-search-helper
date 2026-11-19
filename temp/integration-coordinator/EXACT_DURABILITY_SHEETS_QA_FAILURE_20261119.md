# Exact durability and Sheets boundary QA failure

Date: 2026-11-19

Status: **REJECT — repair and independent re-verification required**

## Scope

Independent read-only QA reviewed accepted local checkpoints `565b798` and
`332b2f9` together. No production source, live database, Google Sheet, lock,
queue, receipt, Jetson service, or job data was changed.

## P0 — remote intent and acknowledgement authority was caller asserted

`SheetsSynchronizer.publish_exact_scope` trusted caller-supplied
`intent_state='SYNC_PENDING'` and `first_attempt=True`. Repeating the same call
with the same IDs invoked `remote.commit` twice because the API did not query
or atomically consume a durable single-use intent. The disposable adversarial
result was `{'commit_calls': 2, 'batches': 1}`; the second fixture operation
happened to be a no-op, but the remote request was replayed.

`acknowledge_exact_scope` likewise accepted caller-constructed readback plus an
unkeyed deterministic digest and arbitrary receipt ID without proving that the
publication receipt was `SYNC_CONFIRMED`. A disposable zero-remote-write case
successfully acknowledged and cleared selected local dirty state while Google
remained blank: `{'ack': False, 'remote_next_action': '', 'dirty': []}`.

Required repair:

- Persist receipt, plan, projection, intent, and attempt binding in the inbox.
- Atomically authorize/consume the first remote attempt exactly once.
- Every subsequent or uncertain invocation must be readback-only.
- Local acknowledgement must query the real inbox and require the same exact
  receipt/plan/projection in `SYNC_CONFIRMED` with the stored acknowledgement
  ID before changing baseline or dirty state.
- Add adversarial duplicate-call and fabricated-zero-write-ack tests.

## P1 — estimated salary guard was omitted from reconstructed projection

The version-2 planner correctly preserved a plausible existing salary estimate
when extracted posting pay was blank: it removed salary mutation and retained
a visible `Salary / Range` expected guard in the frozen remote projection and
row scope. Exact Sheets reconstruction generated `expected` only for mutated
fields, omitting that guard, so equality failed with
`ValueError: Exact Sheets scoped plan differs from the frozen projection.`

Required repair:

- Reconstruct all frozen remote-visible expected guards, including the salary
  estimate, from the explicit row scope.
- Keep local-only Source Hash evidence as a local prewrite guard; never emit it
  as a compact Google field.
- Add a blank-posting/retained-estimate exact projection equality test.

## Passing evidence that did not override the defects

- Combined focused/adjacent boundary matrix: 166 tests passed in 12.177s.
- SQLite/local-pipeline matrix: 87 tests passed in 24.871s.

Those suites lacked the adversarial cases above and therefore were not
acceptance evidence for deployment.

## Repair ownership

- Inbox/sync/recovery lane: durable single-use intent, confirmed receipt
  authority, recovery wiring, and duplicate/forged-boundary tests.
- Exact-Sheets lane: mandatory durable authority consumption, receipt-confirmed
  acknowledgement, salary guard reconstruction, and scoped API tests.
- Coordinator: reconcile both lanes, reproduce tests, assign independent QA,
  refresh the protected production staging candidate, and keep all live action
  disabled until acceptance.

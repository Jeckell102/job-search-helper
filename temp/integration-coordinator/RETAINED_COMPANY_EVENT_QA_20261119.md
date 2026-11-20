# Retained Company-event route independent QA — REJECT

## Scope

Activation-rejecting, read-only review of `retained_company_event.py`, its
runner command, its dedicated tests, and the existing retained primitives. No
service, Sheets access, protected source, or live scraper was used.

## Must-fix 1: the route self-deadlocks on the normal scraper lock

`run_retained_company_event()` holds `writer_lock(root / scraper_lock_name())`
for its entire body at `retained_company_event.py:54`, then calls
`commit_exceptional_start()` at lines 91-93. That primitive independently
acquires the same lock at `retained_work_runner.py:628-629`. After the writable
factory phase, it also calls `run_retained_reservation()` at lines 105-107,
which acquires the same lock at `retained_work_orchestrator.py:66-67`.

The lock is not re-entrant: two independent file descriptions in one process
cannot both take nonblocking exclusive `flock` locks. A small local
reproduction returned `BLOCKS`. The current route test patches `writer_lock`
to `nullcontext`, so it cannot expose the production deadlock. Define one lock
owner per call path (or use explicitly locked primitive variants) and add a
real-lock regression that reaches both the initial freeze and reservation.

## Must-fix 2: a signed exception cannot become active through an operational CLI

The production route correctly constructs an Ed25519 public-key verifier and
`_active_record()` re-verifies the persisted envelope and expiry. But the
runner exposes only `retained-exception-preview` and
`run-retained-company-event`. There is no command/API path that accepts a
signed envelope, invokes `activate_exception()`, and durably creates the
required active exception record before the run command. The run command
therefore requires an active record that an operator cannot create through the
documented CLI. Add a narrow activation command with exact manifest/envelope
input, public-key verification, expiry validation, idempotent durable receipt,
and tests with a real Ed25519 signature plus expiry failure.

## Must-fix 3: settled retained work leaves the bridge request for normal replay

The retained orchestration settles its retained-start journal only after
`FIRST_PASS_RELEASED`, which is correct. However, neither
`retained_company_event.py` nor the retained orchestrator removes or archives
the exact `next-scan.json` request, nor records a settlement-bound bridge
consumption receipt. Once the retained journal is settled, a subsequent normal
start can still consume that acknowledged bridge request through
`requested_scan()` and create ordinary duplicate work.

Remove/archive only the exact request (bound to the immutable request digest,
event receipt, and retained reservation) after durable FIRST PASS release and
retained-journal settlement; preserve it on every earlier state or failure.
Add crash/retry tests on both sides of that transition.

## Must-fix 4: CLI returns success for `SYNC_PENDING`

`run_retained_company_event()` returns the publication state unchanged, and
the runner prints it then unconditionally returns exit code zero at
`runner.py:1119-1125`. `SYNC_PENDING` therefore appears as a successful
command even though release/settlement has not occurred. The dedicated test
explicitly accepts that internal state. Make the command return a non-success,
clearly retained/pending outcome unless the final state is exactly
`FIRST_PASS_RELEASED` with settlement evidence.

## Positive observations

- The retained primitives enforce canonical one-company bridge request and
  receipt identity, a single unfinished blocker, and provider/name/URL
  disjointness before admitting the exception.
- The normal path uses read-only State preflight before local/remote factories,
  does not construct a normal Inbox, and uses exact retained publication rather
  than the global synchronizer.
- The active exception record checks real Ed25519 public-key material and
  revalidates the signed envelope/expiry before mutable reservation work.
- Existing retained publication primitives gate journal settlement on durable
  `FIRST_PASS_RELEASED` evidence.

## Evidence

Strict retained command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -W error -m unittest tests.test_retained_company_event tests.test_retained_work_exception tests.test_retained_work_runner tests.test_retained_work_orchestrator tests.test_retained_work_publication`

Result: **61 tests passed**. The dedicated route tests use mocked locks and
factories, so they do not exercise the nested-lock, actual signed activation,
or post-settlement request-consumption boundaries above.

## Follow-up after must-fixes

After the four blockers are repaired, add end-to-end temporary-state tests for
an actual Ed25519 envelope, expiry rejection, real lock acquisition, exact
request archiving only after settlement, pending exit status, and lost-response
idempotent recovery.

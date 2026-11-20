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

---

# Final remediation re-review — REJECT (supersedes the earlier rejection)

The four original route defects are closed in source:

- The entry point no longer holds an outer scraper flock while calling the
  retained primitives that own that lock themselves. Its real-flock regression
  now reaches a commit hook that takes the actual lock without deadlocking.
- A settlement-bound consumption transition archives the exact request, removes
  only that same current request, records a durable consumption receipt, and
  recovers archive/unlink/receipt interruptions without factories or replay.
  It preserves a different newer request and ignores completed archives.
- Consumption requires `FIRST_PASS_RELEASED` plus settlement evidence; the
  runner exits nonzero for `SYNC_PENDING` and zero only for released work with
  a consumption receipt.
- `activate-retained-exception` supplies an explicit public-key-only CLI route
  and takes the normal scraper lock while it revalidates current evidence and
  freezes the active record.

## Remaining must-fix 1: actual Ed25519 activation is not runnable in this runtime

The project declares `cryptography>=50,<51`, but the active Python 3.11
runtime resolves the system `cryptography 3.4.8`, whose Ed25519 backend fails
to import because `_cffi_backend` is missing. The direct Ed25519 smoke check
and the suite's real-signature test both fail before signature verification.
Consequently the new activation command cannot be release-accepted as an
operational real-Ed25519 route here. Run this route/tests in the project
environment with the declared dependency installed and add that environment to
the release evidence; do not treat test-only verifier coverage as a substitute.

## Remaining must-fix 2: CLI does not provide the exact activation bundle it requires

`activate-retained-exception` requires an approval file containing both the
full `manifest` and signed `envelope`. But `retained-exception-preview` prints
only `manifest_digest` and `required_claims`; it deliberately withholds the
full manifest. No documented CLI/API in this port writes or exports the exact
manifest that the external signer must return in the approval bundle. The
operator therefore cannot complete the advertised preview -> external-sign ->
activate path using the public interface alone.

Provide a narrow, durable/exportable approval-bundle preparation path (or
change activation to rebuild the manifest locally and accept a signed exact
claims envelope), with tests proving the signer cannot substitute a different
manifest. This is required for the new command to be operationally activatable.

## Follow-up (not a release blocker once the above is resolved)

- Add runner-level tests for malformed activation/run arguments and both final
  exit codes. These command parsers currently let `argparse` raise
  `SystemExit`, unlike the preview command's explicit return-code handling.
- Add a full real-Ed25519 activation-bundle test in the supported project
  environment, including expired and tampered envelope cases at the public CLI
  boundary.

## Final evidence

Source-only retained suite excluding the unavailable real-Ed25519 backend:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -W error -m unittest tests.test_retained_company_event tests.test_retained_work_exception tests.test_retained_work_runner tests.test_retained_work_orchestrator tests.test_retained_work_publication`

Result: **73 tests passed**.

Adding `tests.test_selected_recovery_integration` ran 92 tests but failed the
one real-Ed25519 test at backend import with
`ModuleNotFoundError: No module named '_cffi_backend'`. A direct
`Ed25519PrivateKey.generate()` smoke check fails identically. A separate
runner-boundary check confirmed `SYNC_PENDING` returns exit 1 and released
work with consumption returns exit 0.

---

# Final production-runtime re-review — ACCEPT (supersedes the prior rejection)

The earlier crypto finding was caused by using the system interpreter rather
than the actual `job-search-scraper` wrapper runtime. The production wrapper
uses `/home/chris/job-search-helper_old/.venv/bin/python`, where
`cryptography 50.0.1` and its CFFI backend are present. A direct Ed25519
generate/sign/verify smoke check passed there.

## Verified final behavior

- `retained-exception-preview --output FILE` atomically writes a mode-0600
  signer-input artifact containing the exact manifest and required claims.
  The external signer can return the documented `{manifest,envelope}` approval
  file to `activate-retained-exception`.
- The public activation test uses a real Ed25519 key in the wrapper runtime,
  activates the exact bundle, and rejects altered claims, a wrong public key,
  and a correctly signed expired payload. Activation takes the normal scraper
  lock and revalidates current manifest evidence before freezing the record.
- The route no longer nests the scraper flock around primitives that own it;
  its real-lock test passes. It still uses read-only authority opens before
  writable factories and no normal Inbox/global sync.
- Exact post-settlement request consumption is bound to the archived request,
  retained admission, and released publication. Archive/unlink/receipt crash
  recovery converges idempotently, completed archives are skipped, and a
  differing newer request is retained.
- Request consumption requires durable `FIRST_PASS_RELEASED` plus settlement
  proof. `SYNC_PENDING` produces nonzero CLI exit status; only released work
  with a consumption receipt exits zero.

## Evidence

Production-runtime strict command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_retained_company_event tests.test_retained_work_exception tests.test_retained_work_runner tests.test_retained_work_orchestrator tests.test_retained_work_publication tests.test_selected_recovery_integration`

Result: **93 tests passed**. Expected negative activation attempts emitted
their error messages and were asserted as failures by the test.

## Follow-up

Consider minimizing the successful activation command's console JSON: it
currently includes the complete returned manifest/envelope. This is not an
authority or correctness blocker (no private key is accepted or printed), but
a receipt summary would reduce unnecessary local exposure of retained evidence.

## Privacy follow-up re-review — ACCEPT

The activation success path now prints only a receipt containing state, exact
cycle ID, manifest and authorization digests, key ID, and authorization expiry;
it no longer echoes the full manifest or signed envelope into terminal output.
The regression captures stdout and asserts that exact six-field receipt while
excluding both sensitive structures. The production-wrapper focused command
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_retained_work_runner tests.test_retained_company_event`
passed **40 tests**. The prior final ACCEPT remains in force.

## Environment-interface follow-up — REJECT

The committed environment route correctly loads the named variables after
environment loading, omits key material from normal output, and fails closed
for absent or malformed configuration. However, it does **not** preserve an
intentional explicit manual override when
`COMPANY_RETAINED_SHEET_REQUEST_INTERVAL` is malformed: the parser eagerly
evaluates `float(os.environ[...])` while constructing its default, before it
parses `--sheet-request-interval 1.2`. With valid manual key/public-key/interval
arguments and environment interval `not-a-number`, the command returned 1 and
never called the production route. Defer environment interval conversion until
after parsing (using the environment value only when the option was omitted),
then add this override regression. Focused production-wrapper tests otherwise
passed **41 tests**. This finding supersedes acceptance for the tiny env
interface only; it does not reopen the retained-route acceptance above.

## Environment-interface repair re-review — ACCEPT

The interval is now parsed from the command line first and consults/converts
`COMPANY_RETAINED_SHEET_REQUEST_INTERVAL` only when that option is omitted.
The new regression proves a malformed environment interval cannot block a
fully explicit manual key, public-key, and `--sheet-request-interval 1.2`
invocation; the production call receives 1.2. Missing configuration and
environment-only validation remain fail-closed. The production-wrapper narrow
command `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_retained_work_runner`
passed **23 tests**. This supersedes the environment-interface rejection.

## Remediation update — 2026-11-19

The dedicated route now keeps `commit_exceptional_start()` and
`run_retained_reservation()` as the sole owners of their non-reentrant scraper
lock scopes.  The outer route lock was removed; a real `flock` regression
proves the commit boundary can acquire the lock after the short recovery check.

Bridge consumption is now archive-first and fsynced.  The ordinary post-release
archive/read/unlink/receipt transition runs under the scraper lock.  A restart
with a missing receipt examines exactly one pending archive before any factory
or fetch.  It requires the archive filename digest, frozen admission payload
digest/request digest/event/company/cycle/manifest identities, active matching
exception record, and `FIRST_PASS_RELEASED` retained-publication row with valid
queue-evidence digest.  It then records the old receipt without removing a
different newer `next-scan.json`.  Completed archives are ignored; malformed,
ambiguous, changed, or insufficiently proven pending archives are held.

Activation now holds the scraper lock from cycle read through manifest
revalidation, Ed25519 verification, and exception-store freeze.  A real lock
contention test proves it fails before State/store mutation.

Current focused/adjacent evidence:

`PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_retained_company_event.py tests/test_retained_work_exception.py tests/test_retained_work_runner.py tests/test_retained_work_orchestrator.py tests/test_retained_work_publication.py tests/test_company_event_bridge.py tests/test_company_event_outbox.py tests/test_company_intake_dispatcher.py tests/test_company_intake_handoff.py tests/test_sync_cli_lifecycle.py`

Final run: **124 passed** and `git diff --check` was clean.  The final
assertions additionally require read-only recovery authority opens, the shared
canonical bridge-request validator, and a settlement record before fresh-path
consumption; a nominal `FIRST_PASS_RELEASED` string alone is rejected.

## Signer handoff remediation

`retained-exception-preview --output FILE` now atomically emits a mode-0600,
fsynced/read-back signer-input JSON containing exactly `{manifest,
required_claims}`.  Console output remains limited to the manifest digest and
claims.  An external signer must return a separate activation JSON object
`{manifest,envelope}`, preserving that exact manifest and using an Ed25519
envelope over `required_claims`; the activation CLI accepts only a public key.
The project venv smoke-tested `cryptography 50.0.1` Ed25519 and an offline
preview-command -> real signature -> activation-command test, with mutated,
expired, and wrong-key envelopes rejected.

# Automatic retained Company-event supervision — independent release QA

## Verdict: REJECT

This is not ready for an activation or source checkpoint that claims crash-safe
automatic retained supervision.  The separate durable gate, public-command-only
shape, exact receipt checks, post-writer-lock watch placement, and intake-error
containment are sound in the paths inspected.  The release blocker is a real
duplicate-child crash window, and the claimed signed-preflight boundary has not
been exercised end-to-end.

## Must fix 1 — a crash after `Popen` can launch a second retained child

`_spawn_retained()` invokes the public command first and only then reads the
PID start identity and writes `RETAINED_CHILD_ACTIVE`
([company_intake_dispatcher.py:316-332](../../src/job_search_helper/company_intake_dispatcher.py)).
If the supervisor dies in that interval, the durable row remains
`RETAINED_STARTING` without PID/start evidence.  On restart,
`_reconcile_retained_ownership()` sees no live child evidence and calls the
public retained command again ([company_intake_dispatcher.py:226-247]).  That
violates the required no-duplicate guarantee for the explicit “after spawn,
before journal update” crash window.

I reproduced the interleaving with the production wrapper runtime by making a
real `/bin/sleep` child start, interrupting the parent before its PID journal
write, creating a fresh dispatcher, and running the same retained tick:

```
child_launches_after_crash_before_pid_journal= 2
```

The smallest safe repair is a durable launch handshake that the child itself
records before performing retained work, paired with restart reconciliation of
that child-owned record.  A parent-side post-`Popen` update cannot close the
window.  The recovery path must hold/reconcile that exact launch record, never
blindly start a second command.

## Must fix 2 — no real signed preflight test

The only test claiming the valid retained path patches
`_retained_eligibility()` ([tests/test_company_intake_dispatcher.py:90-98](../../tests/test_company_intake_dispatcher.py)), so it does not prove the
required chain of real configured key -> verifier -> active signed exception ->
expiry -> one unfinished exact cycle -> manifest revalidation.  Add at least
one production-wrapper integration test that creates a real Ed25519 signed
ACTIVE record and matching local state/evidence, then proves one retained
public command is admitted; its mutated/expired/wrong-key/wrong-cycle variants
must hold without a child.

## Evidence checked

- Both normal and retained gates are default-disabled and separately persisted;
  the retained command contains only the absolute wrapper path and
  `run-retained-company-event`, not key material.
- Retained receipt validation requires the exact archived request and exact
  `FIRST_PASS_RELEASED_CONSUMED` receipt, and leaves a different current
  request untouched ([company_intake_dispatcher.py:346-363](../../src/job_search_helper/company_intake_dispatcher.py)).
- `sync watch` invokes intake after releasing `writer.lock`; `once` is excluded;
  intake and intake-journal errors stay outside the sync error/backoff path
  ([sync_cli.py:136-158](../../src/job_search_helper/sync_cli.py)).
- Strict production-wrapper suite passed:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_company_intake_dispatcher tests.test_sync_cli_lifecycle tests.test_company_intake_handoff tests.test_company_event_bridge tests.test_retained_company_event tests.test_retained_work_exception
Ran 83 tests ... OK
```

Passing tests do not cover the duplicate-child interleaving above.

## Superseding re-review — REJECT

The original post-`Popen` gap is materially improved: the durable random owner
token is supplied only through the child environment, and a **fresh dispatcher
instance** successfully adopted a real running child rather than launching a
second one:

```
fresh_dispatcher_result= RETAINED_CHILD_ACTIVE adopted_pid= 6 actual_pid= 6
```

The positive signed-preflight test is now genuine: it creates an Ed25519 key,
an ACTIVE signed exception, State cycle, and local manifest evidence before
calling `_retained_eligibility()`.  I also directly confirmed wrong-key and
wrong-cycle preflight attempts raise `ValueError`; an expired authorization is
rejected at activation with `ValueError`.

However, two required process-identity checks remain absent, so this cannot be
accepted as strict automatic supervision.

### Must fix 1 — zombie is considered live forever

`_pid_is_exactly_live()` only compares PID and `/proc/<pid>/stat` start time
([company_intake_dispatcher.py:407-409](../../src/job_search_helper/company_intake_dispatcher.py)).
It does not reject a zombie state.  A real exited, unreaped child demonstrated:

```
proc_state= Z exactly_live= True
```

The dispatcher then reports `RETAINED_CHILD_ACTIVE` indefinitely rather than
recovering the missing/dead child.  Read and reject the process state (`Z`),
with a regression that places a matching persisted PID/start identity on a
zombie and proves public recovery, not active status.

### Must fix 2 — adoption does not verify same UID or exact public argv

Despite its docstring, `_adopt_retained_child()` reads no UID from
`/proc/<pid>/status`; it only matches the token, two independent argv elements,
and CWD ([company_intake_dispatcher.py:518-535](../../src/job_search_helper/company_intake_dispatcher.py)).
It accepts extra/mutated arguments and any executable that presents
`job_search_helper.runner` plus `run-retained-company-event`.  The included
test itself starts a **fake** `job_search_helper.runner` from `PYTHONPATH` and
is accepted ([tests/test_company_intake_dispatcher.py:142-165](../../tests/test_company_intake_dispatcher.py)).

Require the process effective UID to equal the dispatcher UID, reject zombie
state, and require the precise expected public runner argument vector (no
extra operands) before adoption.  Add forged foreign-UID, fake/extra-argv, and
zombie regressions.  Do not treat a token match alone as executable identity.

The strict production-wrapper adjacent suite nevertheless passes:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_company_intake_dispatcher tests.test_sync_cli_lifecycle tests.test_company_intake_handoff tests.test_company_event_bridge tests.test_retained_company_event tests.test_retained_work_exception
Ran 85 tests ... OK
```

Those tests do not exercise the two negative process-identity conditions above.

## Final identity-hardening re-review — ACCEPT

This supersedes the rejection immediately above.  The adoption boundary now
requires the durable owner token, same UID, exact wrapper-spelled argv, matching
resolved `/proc/<pid>/exe`, exact project CWD, and first `PYTHONPATH` entry
equal to the project `src`; it rejects zombie/X process states.  The venv
symlink correction is sound: it preserves the wrapper's `/proc/cmdline`
spelling while resolving `/proc/exe` independently.

The new tests reject a token-bearing fake runner whose `PYTHONPATH` leads to an
untrusted module, accept a faithful isolated wrapper process, and reject a real
zombie.  The owner token remains durable in the local journal and is passed
only through child environment; it is absent from status and command arguments.

I additionally exercised the required full restart path—not merely the helper:
a fresh dispatcher `run_once()` adopted the exact live isolated wrapper child
without another launch:

```
fresh_run_once= RETAINED_CHILD_ACTIVE stored_pid= 6 actual_pid= 6
```

And a stale/dead persisted PID/start identity safely entered the public
recovery route exactly once:

```
dead_child_run_once= RETAINED_CHILD_LAUNCHED recovery_launches= 1
```

Strict production-wrapper adjacent verification passed, with warnings treated
as errors:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_company_intake_dispatcher tests.test_sync_cli_lifecycle tests.test_company_intake_handoff tests.test_company_event_bridge tests.test_retained_company_event tests.test_retained_work_exception
Ran 87 tests ... OK
```

No release-blocking issue remains in the requested retained-supervision scope.

# Sprint 3 staged retained-admission repair

**Staged for review. Samtec remains held.** This candidate corrects a
supervised route's premature blocker rejection and moves locally provable
conflict checks ahead of provider fetch. The existing historical-membership
rule still rejects Samtec. The candidate changes no admission policy and
does not provide or activate an approval.

## Scope

- The retained public command calls the existing
  `_unfinished_cycle_ids(..., include_remote=False)` before constructing
  either repository. Superseded State rows no longer accidentally count
  as independent blockers. Zero or several effective local blockers
  still fail closed. The later full blocker check still includes the
  local workbook mirror and remains in both prefetch and postfetch paths.
- The read-only prefetch check verifies the existing signed/active
  manifest, live local historical evidence, exact request receipt,
  current eligible Company, historical membership, normalized Company
  name, configured endpoint, and any locally resolved source/board alias.
  It shares the signature, provenance, and disjointness logic with final
  admission. It performs no reservation, provider call, workbook factory
  construction, or historical State change. Local source repair and
  board parsing use the normal source resolver.
- Postfetch admission still requires the actual returned source and
  provider identity. Unknown provider identity discovered after the
  request can still reject admission. The existing snapshot checks,
  reservation seal, freeze, and recovery path remain in place.
- Samtec's overlap remains an independent hold after the 19-row raw
  count is corrected. No scope relaxation, production fetch, activation,
  network, Google, database write, or service change was performed.
  Tests used disposable local databases and a disposable Ed25519 key in
  the integrated rejection case.

## Source pins

| File | Production SHA-256 | Candidate SHA-256 |
| --- | --- | --- |
| src/job_search_helper/retained_company_event.py | 23a63941f6fad00ec21376fbb2fd394573db9f8a4a12266ceb7a498781a714cf | cdfade3a00c00e2e71ae410454c123e09b8655935ce097d9fe36d0fe27945e27 |
| src/job_search_helper/retained_work_exception.py | 6454a88349ddf3f4dce8ab853d8bf6577253301f36234a1394a4ac02eb5d7ee9 | 3f02d66fd1817164fcd813a715fad7af32562a970ba367366dbc1570bf10a078 |
| src/job_search_helper/retained_work_runner.py | f57cf819aaf4423fe25802d56151a07145aba070ea1601f3d68dd7f49b4d8785 | 204420aba1f30d24fc3c3220989735381082f7ac4cf9385e8c33aefd14eb4f7d |
| tests/test_retained_company_event.py | b8e0e3b0578625c0405eaf327587be6f25c478f70439982ba88e311e05ca7ea4 | 6ec99793c335833e2ecd01ff5a1644d6801332503e55388270959c95df438fd3 |
| tests/test_retained_work_runner.py | 09a12e617c13b2b480fe9b6d6ebcc1b72e1632617f527bee0e1b16e3b6e096ce | 9e3d19bd0ff07d8144f84de725da459d3528eb40ace4f7b0d8d577fb6c69dadf |

The [five-file patch](/tmp/jsh-s3-admission-candidate/REVIEW.patch)
applies cleanly to the measured production source in a read-only
`git apply --check`. No production patch was applied.

## Verification

The focused cases exercise the superseded-versus-effective State blocker,
rejecting extra effective and workbook-mirror blockers, genuine signed
operator overlap through the retained public function, Company aliases,
requested/returned source aliases, static source-repair aliases, and
provider aliases known locally or first disclosed by the provider response.

A broader SQLite-mode regression group produced **301 passed, 10 failed**
on the candidate and **294 passed, 10 failed** on an otherwise identical
unmodified production copy. The 10 failing test identities matched exactly.
They were in normal bridge/runner exact-sync, exact-cycle recovery, and F3
bootstrap fixtures. The candidate adds seven passing cases and introduced
no failure in that comparison. The production checkout was used only as
the source of the comparison copies.

Both broad runs used the same Python and options from their respective roots:

```sh
env JOB_STORAGE_BACKEND=sqlite PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q \
  -p no:cacheprovider --tb=no tests/test_retained_*.py \
  tests/test_operator_company_request.py tests/test_company_intake_dispatcher.py \
  tests/test_company_intake_handoff.py tests/test_fresh_scan_request.py \
  tests/test_company_event_bridge.py tests/test_company_event_outbox.py \
  tests/test_runner_cycles.py tests/test_exact_cycle_recovery.py \
  tests/test_exact_cycle_sync.py tests/test_run_scoped_sync.py \
  tests/test_release_admission_bootstrap.py
```

The final focused SQLite-mode run passed **147 tests** across retained
admission, orchestration, publication, session and dirty provenance,
operator queueing, intake dispatch/handoff and fresh scan requests. The
candidate's generated test lock was removed after verification.

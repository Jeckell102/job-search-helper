# Sprint 4 ordinary Company-event dispatcher

The disposable candidate is `/tmp/jsh-s4-ordinary-dispatch.EbGqsxme`. Transfer only these three files.

- `src/job_search_helper/company_intake_dispatcher.py`
- `tests/test_company_intake_dispatcher.py`
- `tests/test_ordinary_company_event_dispatch.py`

## Launch and restart

The existing intake gate is still default off. The retained and temporary-retry gates remain separate. An enabled idle tick verifies the exact queued bridge receipt and current outbox source before claiming one request in the existing dispatcher journal. It commits both the dispatch claim and ordinary request ownership before calling the public launcher.

```text
./job-search-scraper ordinary-company-event admit-fetch --request-sha256 SHA256
```

An ordinary tick never uses generic start, generic resume, a first-pass handoff, or an automatic publish. The dispatcher leaves a durable claim after a lost spawn acknowledgement, missing child, nonzero child return, or interrupt. It does not automatically retry that claim. The first child status describes launch or return only. A different queue pointer, a completed old controller, or terminal State alone cannot complete this claim. A matching durable pre-archive cycle safe for the exact command is pinned for a reviewed admit-fetch continuation. A claimed provider observation without a frozen result holds without offering a fetch or publish command. Corrupt, missing or mismatched evidence remains held.

The dispatcher marks ordinary settlement only when exact archived admission and frozen observation, the immutable Jobs outcome, terminal State, the SQLite mirror, and the applicable publication or no-publication proof all agree. It leaves receipt-v1 delivery under its existing ownership. Retained/operator requests and other effective unfinished cycles remain held. A verified exact continuation can coexist with a different queued operator request without replacing it.

## Publication supervisor boundary

`CompanyIntakeDispatcher.reconcile_ordinary()` can use a canonical read-only Jobs repository. It examines existing normal claims and writes only a verified dispatcher transition. It does no bridging, generic lifecycle work, process launch, or remote access. It returns `None` when enabled with no ordinary claim, and `DISABLED` when the ordinary intake gate is off. `status()` includes `ordinary_handoff` when its journal ownership agrees.

A frozen, exact observation yields `HELD_ORDINARY_PUBLICATION` with the argument list for `ordinary-company-event publish --request-sha256 SHA256 --cycle-id CYC-ID`. A reviewer can invoke this command explicitly. With no observation, an exact review may resume admit-fetch. The existing watcher only ticks intake after broad sync, while both watcher startup and the sync loop can defer before reaching that tick when a guarded ordinary cycle is active. An uninterrupted supervisor needs a separate read-only call to `reconcile_ordinary()` outside the broad sync guard and before opening a Sheets writer. Keep the existing broad hold. This change offers no auto-publish approval. A future automated publisher needs an explicit gate, a separate durable launch claim bound to the same verified digest, saved cycle and observation, operation under the exact public command's inherited leases, and terminal readback before it can release ownership. A legacy ordinary controller workflow is reported as held for review instead of being resumed through generic start.

## Verification

**75 focused offline tests passed.** The selection covers the dispatcher, public exact command, provider observation, exact publication, typed no-publication settlement and legacy temporary handoff. Fixtures use disposable SQLite, fake Sheets and a fake provider. The composed dispatcher tests prove exact outbox-to-bridge launch, idempotent readback, lock contention, moved pointer and tampered receipt holds, pre-archive exact restart, ambiguous provider cut, confirmed publication and temporary no-write outcomes, immutable outcome enforcement, and unrelated operator/manual-retained isolation.

```bash
env JOB_STORAGE_BACKEND=sqlite PYTHONPATH="$PWD/src:$PWD" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$PWD/t-release-check" --tb=short \
  tests/test_ordinary_company_event_dispatch.py tests/test_company_intake_dispatcher.py \
  tests/test_ordinary_company_event_command.py tests/test_ordinary_company_event_fetch.py \
  tests/test_ordinary_company_event_publication.py tests/test_ordinary_event_no_publication.py \
  tests/test_company_intake_handoff.py
```

The additional legacy F1 composition run produced five failures. Its idle callback hardcodes generic start and needs migration. Four other cases reach the isolated baseline's absent dependency manifest before the relevant runner step. Those fixtures were outside this dispatcher's owned files. No production files, credentials, services, network, GitHub, Jetson, live data, or feature flags were accessed or changed.

## Candidate hashes

- `7beec86a3810aaf074a1c35529a0724d45a95b7a02a06a4481c6d65d34e93964` for `src/job_search_helper/company_intake_dispatcher.py`
- `59b766162db1948d3d0b40384236b2fccf40c21c63867b5139f9db79d9a8ee04` for `tests/test_company_intake_dispatcher.py`
- `0735bae1735e7e28567223bf068cdcbe486787689eb2c483acc54f2f58ea2ccc` for `tests/test_ordinary_company_event_dispatch.py`

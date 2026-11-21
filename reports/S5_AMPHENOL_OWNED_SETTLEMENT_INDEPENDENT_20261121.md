# Independent ordinary AcquireTM settlement QA — 2026-11-21

**ACCEPT the exact source-only ordinary Company-event settlement slice.**
No blocking gate failure was found. This is not deployment, automatic task
launch, generated-wrapper acceptance or operator-origin admission evidence.

Author tree: `/tmp/jsh-s5-acquiretm-ordinary-settlement.C97xg7dL`.
Independent copy/probes: `/tmp/jsh-s5-acquiretm-settlement-independent.kwxds9ct`.

## Exact reviewed pins

| File | SHA-256 |
| --- | --- |
| `ordinary_company_event_command.py` | `f8765638f4a437a1a619bfe20161987f63b3f42bf508169850140ef9de0a1d9d` |
| `ordinary_company_event_publication.py` | `ca34435dad229dd637f0470e1aa39cca98d298583ce6ece2e33f9c3fdca1c85c` |
| `ordinary_event_settlement.py` | `5d99a2674d7a6db844fbdd5da0a1ac037a254130cde4112fde4ac8b9b1c1d16f` |
| `runner.py` | `1583f5b286cb0c54566d9933237e934406a0c123d467663ab718bc60c091299c` |
| `tests/test_ordinary_event_no_publication.py` | `b5a9515c83000445dd555e5320482be4d968623f168dfce38c3f85d9136a5d1a` |
| `acquiretm.py` (accepted dependency) | `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61` |
| `ats.py` (accepted dependency) | `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e` |
| `tests/test_acquiretm.py` (accepted dependency) | `dca8d436b5c7840beecba2c14b6ffc01d4d279adab3a5fb5083d681713d891f1` |

Application basenames above are under `src/job_search_helper/`. All eight
pins matched before execution. The reviewed four implementation deltas are
limited to the ordinary event's publication decision, qualified local-only
settlement/readback and successful named-command exit status.

## Acceptance evidence

- **89 maintained tests passed in 12.95 seconds**, independently rerun:
  ordinary no-publication, fetch, publication, receipt binding, dispatcher,
  typed AcquireTM and retained Company-event suites.
- The composed normal-command fixture creates a transactional eligible event,
  admits the exact request, invokes the actual adapter against the simulated
  delayed browser and freezes the typed partial. With a cut after Jobs commits
  and before State saves, receipt delivery remains held. Replay saves State
  and returns the same single canonical qualified outcome. The existing
  sender records one accepted receipt and replays without another sink call.
- Publication preflight, lower publisher and settlement agree on the local-only
  branch. Foreign Company, untyped repeat, malformed witness and a typed result
  contaminated with jobs cannot qualify; the contaminated branch opens no
  Sheets writer. The valid branch leaves Company Partial and cycle Complete
  with exceptions, with no Job History or Job Evidence projection and no
  workbook write. The workbook reader and local control updates are exercised.
- **Three independent probes passed in 6.37 seconds.** A Company source change
  away and back during the workbook read prevents qualification and leaves
  State unfinished. The same revision sequence after settlement prevents
  terminal-currentness acceptance and delivery while preserving the original
  outcome. Replacing the frozen witness with a syntactically valid changed
  timing value and recalculated inventory/record hashes fails exact settled
  readback and delivery. No sink is called in these refusal cases.

The receiver in the composed fixture is a deterministic receipt-v1 stub.
This proves the real sender's one-receipt behavior, not a new live coordinator
receiver observation or automatic repair task. The independent extra probes
use a typed synthetic failure and real disposable admission/storage helpers;
the maintained composition supplies the actual adapter fixture.

The generic producer, dispatcher, selected-retry no-publication predicate,
retained settlement and profile registry are unchanged. The new qualification
uses the ordinary owner's verified request, source and frozen observation;
it does not authorize generic partials or another admission origin. Published
and pre-existing no-publication cases retain their existing paths. Existing
contradictory publication archives/chunks remain settlement blockers.

## Runtime and limits

Final runs used explicit `/usr/bin/python3.11` (3.11.18), `-I -S -B`, private
source/tests, copied pytest support and existing system cryptography packages.
A Python audit hook refused socket connection, bind and DNS operations.
Initial QA runner setup issues (default Python 3.10 missing test support and
a missing copied bootstrap) were corrected only in the independent harness.
The extra fixture initially passed a string instead of a Path to the existing
admission helper; its test-only correction preceded the passing run. No
candidate source was edited to satisfy a test.

All SQLite and workbook objects were disposable fixtures. No production,
model, Jetson, Google, network, service, task or release action occurred.
Actual runtime/lease measurement and live event authority were substituted at
the maintained fixture boundary; deployed acceptance remains separate.

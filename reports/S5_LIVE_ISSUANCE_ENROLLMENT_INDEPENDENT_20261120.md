# Independent read-only issuance enrollment review

Source decision: ACCEPT for the documented snapshot-helper contract. No concrete source defect found. All 24 distinct maintained/independent tests passed across the completed runs described below. This report does not approve deployment or a live issuer.

Candidate: `/tmp/jsh-s5-issuance-enrollment.OSygejTK`.

| Reviewed file | SHA-256 |
|---|---|
| `src/job_search_helper/ordinary_live_issuance_enrollment.py` | `0c676bda8e5eab517254cc923473bc4cf492492dc6eb96630fc074ad43f217aa` |
| `tests/test_s5_live_issuance_enrollment.py` | `f4c3bae54e96dca53fe5191a843d487ae8b57bd5ac014bc6408e5805a851ea34` |

Both pins were checked before and after the completed tests. The candidate was not modified.

## Findings and scope

- The supplied independent approval digest is checked against bounded canonical approval bytes before opening stores. The approval's top-level keys, scope, candidate vector, tool hashes, integer limits, and short deadline are closed contracts (`ordinary_live_issuance_enrollment.py:50–70`). A caller-controlled replacement approval cannot satisfy the independently retained original digest.
- The function opens distinct, physically pinned State/Jobs/Inbox stores in read-only mode and binds the workbook (`ordinary_live_issuance_enrollment.py:121`; `ordinary_verification_pending.py:53–106`). `InventoryInbox` uses SQLite `mode=ro` at `inbox.py:125–134`; it intentionally has no public `readonly` attribute.
- `_binding` first verifies the real scraper/writer flocks; it requires an exact archived typed mismatch, a saved runtime equal to the supplied runtime, no immutable outcome, and captured bytes/dispatch/inventory identity (`ordinary_verifier_handoff.py:101–120`). `_published_marker` verifies archived publication and reserved outcome owner (`ordinary_verification_terminal.py:14–25`). Raw capture is reread through the enrolled custody, rather than accepted as a caller result dictionary.
- Current target is exactly COMP-0066 Forterra with its required authority URL. Control is exactly COMP-0178 with the approved PDW label/URL projection. Both must remain Active/Rippling, unique, unclaimed, and not manually held; only the target may carry the selected active cycle. The target installed-source snapshot and current qualification matrix must still match (`ordinary_live_issuance_enrollment.py:74–101`; `ordinary_verification_pending.py:118–139`; `ordinary_verification_worker.py:60–71`).
- Superseded cycles, existing terminal checkpoints, prior outcomes, changed archived bytes, changed capture, current source qualification drift, and expired windows refuse. Exact publication/cycle bytes, Company projections, capture, and held leases are read back again before return (`ordinary_live_issuance_enrollment.py:139–147`).
- The function returns only a binding dictionary. It neither opens a slot nor invokes coordinator enrollment, remote publication, scraping, or verdict approval. Fabricated or stale binding dictionaries alone cannot earn a slot: the retained coordinator checks an independently pinned selection and an existing exact enrolled row (`coordinator_issuance_admission.py:335–366`), and slot admission calls that authority (`ordinary_live_issuance_slot.py:225–248`).

## Required caller dependency

This helper does **not** freshly measure installed runtime/module identity. It documents that the measured application owner supplies the current runtime while holding the ordinary leases (`ordinary_live_issuance_enrollment.py:108–112`). `_binding` and `Engine.validate_cycle_runtime_binding` compare the supplied and saved dictionaries; they do not independently measure source files.

The coordinator confirmed this is intentional: fresh runtime/module measurement belongs to the future measured launcher/caller. That caller must supply independently retained approval and selection pins, freshly prove its runtime under the held leases, validate the returned exact binding, and use the separately reviewed coordinator admission. Candidate/tool hashes remain approved inputs for later measurement. Do not treat the returned dictionary as a live authority, a fresh runtime attestation, or a candidate validation verdict. This integration dependency remains required and was not exercised as a live route here.

## Completed disposable tests

Interpreter: `/home/chris/job-search-helper_old/.venv/bin/python`, used only as an executable with private candidate cwd and explicit staged source/tests paths. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONDONTWRITEBYTECODE=1`, `-B`, and `-p no:cacheprovider` were used. No production application, DB, services, network, or GitHub were used.

- Maintained enrollment tests: **7 passed in 3.60 seconds**.
- Reviewer probe file: `/tmp/jsh-s5-issuance-enrollment-review-probes.py`, SHA-256 `15019c70bd87289e3d15bafb765a6596f2e399b085488552455b134876643482`. **14 probes passed**, covering five altered approval fields against the original independent pin, five current target/control claim/hold/status cases, loss of each actual owned lease at final readback, expiry after readback, and a positive read-only snapshot with remote/slot opening forbidden.
- Three existing authority tests passed: `test_unenrolled_or_stale_frozen_digests_cannot_earn_allowance`, `test_wrong_binding_or_selection_cannot_enroll_or_update`, and `test_selection_requires_separate_private_roots_and_exact_code`.
- Combined second invocation: **16 passed, 1 reviewer harness failure in 8.52 seconds**, approximately 22:23:12–22:23:21 Eastern on 2026-11-20. The failure was an AttributeError from the reviewer assuming `InventoryInbox.readonly` existed, before the snapshot ran. It was not a candidate acceptance failure. The assertion was corrected to follow the actual API and verified SQLite constructor path.
- The corrected single probe then **passed in 1.15 seconds**, using `/usr/bin/python3.11 -I -B`, cwd `/tmp`, explicit staged imports, and copied pytest support packages under `/tmp/jsh-s5-review-pytest-dependencies`. It did not run a production venv executable or use a production cwd. An earlier attempt with the system's older pytest failed at framework import (`apipkg __spec__`) before collection; no candidate test executed in that attempt. Copying only the test framework resolved that environment incompatibility without changing application source.

These are 24 distinct completed tests, not a claim that the coordinator's broader 111-test suite was independently rerun. Tests use synthetic provider responses and a recording remote. They use actual disposable SQLite and real application leases. Source qualification resolution and provider response collection in their fixture are substituted, so these tests are not native installed-source or live remote acceptance. Main application DB bytes stayed unchanged around the reviewed snapshot calls; physical WAL/SHM immutability is not asserted.

No acceptance criterion was weakened, no candidate repair was made, and no deployment or live capability is claimed.

# Independent QA: published repair retry local closeout

2026-11-21. **ACCEPT — exact source/restart seam only.** No native execution or release approval is conferred. Candidate: `/tmp/jsh-s5-exact-retry-closeout.Ss4z8EuB`. All execution occurred in this private scratch; candidate source was unchanged.

## Frozen source and test pins

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/exact_cycle_recovery.py` | `e9ad790842de5d1406f90d816e45ec0bc39fe5b5545e5df8c1a0e09c5758074f` |
| `src/job_search_helper/exact_cycle_receipt.py` | `7602084179e929f0cc06ec664e60ebe30c7afcccbc052d26c490d9060a7b9ce6` |
| `tests/test_repair_retry_closeout.py` | `5ea08ffc8e6915350452b8fed66a160d8671afd573ba1413568b444ef92d22e6` |
| `test_saved_amphenol.py` | `a193eafc4a86b0bcf0a9c211e59a3e8b7de26ecd1dcbe73e6c9e4a62fc726dec` |

Pins were checked against author and candidate before and after the independent run.

## Result and scope

Independent offline run: **10 passed in 20.84 seconds** (`test-results.txt`). It ran the nine maintained closeout cases plus the copied saved-Amphenol proof. System `/usr/bin/python3.11 -I -B` used explicit private source/test paths, disabled plugin loading and bytecode, and an audit hook refused DNS/connect/bind/sendto. A compatibility assignment to the system pytest dependency's `py.__spec__` was runner-only; application and test source were not altered.

The archived disposable input was copied from `/tmp/jsh-s5-amphenol-publication-rehearsal/test-project/.state`, only after checking zero/absent WAL files. State/Jobs/Inbox plus exact release journal and archived request were byte-verified on copy; original file hashes were unchanged after execution. This archive contains actual previously completed disposable publication, not a new real workbook operation.

The exact archived cycle `CYC-8F35E1D030EF`, Company `COMP-0490`, attempt `RTRY-94818009148713cd8859150f`, release `REL-76cc6f8179568b839386f429` reached matching local State and Jobs Scan Cycles `Complete`, added exactly one COMPLETE outcome, and replayed the same outcome. All 18 Job History and Job Evidence rows, Companies, Opportunities, predecessor cycles, preexisting outcomes, Inbox logical contents and confirmed receipt, release journal and archived request were preserved. No next-scan request was created. Fetch was a throwing sentinel; the maintained publication fixture also verified that the prior single remote batch count stayed one. No production application, database, provider, Google, queue, Jetson or service was used.

## Source review and restart contract

- `exact_cycle_recovery.py:233–246` requires concrete local Engine/State/SQLiteRepository/Inbox instances, writable local State/Jobs and their shared configured or canonical local application paths. This does not authorize a different workbook: the existing acknowledgement verifier at `inbox.py:348` compares the durable Inbox destination against Jobs' workbook identity.
- `exact_cycle_recovery.py:248` acquires normal scraper then writer locks, and checks retained lifecycle ownership before changes. Both locks being independently held were proven to stop closeout with State/mirror still In Progress and no outcome.
- `exact_cycle_recovery.py:250–263` rejects superseded/wrong cycles, wrong attempt/release/Company, unsuccessful inventory, changed runtime, or absent confirmed publication before completion writes. `exact_cycle_receipt.py:239` rechecks the active COMPLETE release journal and current Company source revision. Its publication helper at line 271 requires sole repair scope, exact request fingerprint/runtime/source/release, absent residual inventory/plan/remote state, exact SYNC_CONFIRMED receipt schedule and records, unique local application/acknowledgement, and the existing acknowledgement verifier. The default `require_complete=True` preserves existing callers; only this closeout precheck opts into the exact In Progress checkpoint.
- `exact_cycle_recovery.py:285` requires one exact Scan Cycles mirror with matching admitted identity and start time. The normal `_sync_cycle` is used only for the selected local mirror and State; the repository is required to be SQLite. It does not construct a Google client, scrape provider, or run a broad lifecycle.
- Interruption after mirror completion but before State save preserves the mirror's completion timestamp. Replay saves the same timestamp to State, without rewriting the completed mirror. Interruption after State save but before outcome insertion reuses both completed records and writes exactly one outcome. A subsequent successful replay leaves the Jobs logical dump unchanged. An unrelated saved cycle remained exact.
- Wrong attempt/release/Company, missing local acknowledgement and a receipt changed to SYNC_PENDING all held before application state changed. Existing success producer rereads the saved cycle and exact receipt pair, then derives the terminal outcome; callers do not supply fabricated success facts.

## Limits

This validates the application closeout contract and the actual saved disposable 18-job publication. It does not repeat a provider or remote call, claim newly measured native runtime, perform deployment, or authorize any old-cycle reconciliation. Source authority is the existing admitted application/runtime and active release contract; arbitrary in-process replacement of trusted code or database contents is outside this supported-call/restart check. Normal local Scan Cycles bookkeeping includes its existing dirty/commit bookkeeping; no workbook write occurs here. New native execution still requires the coordinator's separately qualified release/admission conditions.

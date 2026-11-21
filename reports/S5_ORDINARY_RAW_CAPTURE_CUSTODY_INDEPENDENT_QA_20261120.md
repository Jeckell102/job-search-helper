# Independent QA of ordinary Rippling raw-capture custody

**Accepted for the exact isolated custody component.** This verdict covers one enrolled private attempt, scoped to the reviewed callback and caller-provided exact PREPARED/Inbox pair. Application admission and leases, the real provider callback, State/Jobs wiring, retention, live collection, and deployment remain separate.

| Reviewed artifact | SHA-256 |
| --- | --- |
| QA manifest | `f861a45954789ec5318090b4fa08e80ca2b6c62ef9a8b0926c5b89e7b378df4f` |
| `src/job_search_helper/ordinary_raw_capture.py` | `b038adffbdf2bac9811806a8aaecf2cb816cebeb2bcce73037447670503ee571` |
| `tests/test_ordinary_raw_capture.py` | `cde3a01936dafb9c9c962e08c74125c0ad7f9933abee81ee816f8f4a1a051b0e` |
| `checkpoints/INTERFACE.md` | `290e7e1d9fefeb63e90a7d04795607d333f53125e8879f3c8d5d2a1977cee8c4` |
| Imported worker `ats.py` | `92a1e43194f02201089e81f5a891fb368f44865f50aeab351d8281fdd0290a20` |
| Imported worker `ordinary_verification_pending.py` | `efda2b34c9550c56bb0e974194a9ce9d82d1db29343ef97c29b5697ff8c20bdd` |

The maintained suite passed 54 tests. The independent probes passed 59 checks. A duplicated directory descriptor remained usable after the caller released its original descriptor. A different named root, a same-inode ancestor symlink, wrong file modes, symlinks/hardlinks and same-byte replacement of each selected file all held. A same-byte body rewrite in place and a replacement between the body read and final identity check also held. A staging path that disappeared or became an alias returned the sanitized custody error with no callback. An exact paired read was reusable, kept the submitted inventory unchanged, and exposed neither the raw content nor private path in its summary representation.

Only one private reservation won a concurrent slot race. Duplicate concurrent offers invalidated the selection. The body size limit accepted exactly six MiB and refused an oversized response, mutable buffer, wrong endpoint, wrong status type, or wrong digest. A changed caller marker after reservation could not repoint the ticket. A complete, blocked, zero, transient, browser-pending/incomplete, foreign-source, nonempty, or unselected final inventory left no sealed body. ARMED, blocked, changed generation, prior observation mismatch, changed inventory, and changed source or capture-policy pin could not export the exact PREPARED capture.

Real disposable processes exited before and after both no-replace publication steps and after each atomic rename but before its parent-directory fsync. A reservation never granted a second callback once its final name existed. An unsealed staged response did not export. A sealed capture without PREPARED did not export. An empty destination inserted at the publication boundary kept its exact inode and contents, and the sealed rename held. These are process exits on the fixture filesystem. Power-loss recovery and hostile same-UID tampering are outside this verdict. No private raw content, real application files, or source overlay edits were used or emitted by the QA.

### Reproduction

From `/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK`:

```sh
sha256sum -c checkpoints/QA_SHA256SUMS
qa_tmp=$(mktemp -d /tmp/jsh-s5-capture-independent-pytest.XXXXXXXX)
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o 'pythonpath=/tmp/jsh-s5-ordinary-worker.akf3gPsM/src' -q --tb=short \
  --basetemp "$qa_tmp/pytest" tests/test_ordinary_raw_capture.py
```

From this report's private directory:

```sh
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_custody_boundaries.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_custody_crash.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_reservation_stage_races.py
```

All commands exited 0. `maintained.log` reports 54 passed in 0.66 seconds. The independent logs record 41 boundary checks, 16 process-exit and contention checks, and two staging-open race checks.

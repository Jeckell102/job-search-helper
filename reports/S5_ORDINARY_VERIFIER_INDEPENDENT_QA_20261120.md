# Independent QA of the ordinary Rippling verifier prototype

**Accepted for the exact offline, owned private-channel prototype.** The verifier can prepare a bounded `offline_saved_captures` receipt for one exact pending identity. This acceptance ends at the private verifier receipt. The normal worker pause, local State/Jobs finisher, publication precedence, qualification, and release are separate gates.

| Verified artifact | SHA-256 |
| --- | --- |
| QA manifest | `dc3e2fec524d31b357a99e48af79eac27a5ddcb52e704647ce02a0dd807a58b7` |
| `dev/ordinary_rippling_verifier.py` | `2925328cfae39a390cbac072a0834d10a580b0174555c1ef00fa9e418f7564c6` |
| `tests/test_ordinary_rippling_verifier.py` | `31611ebe3df5b933f2ab220af7f74447bf520b9f1b122a9a2bb22cf51dce3241` |
| `checkpoints/PENDING_CONTRACT.md` | `5cc349244020b20cb3167d732e1e0c1f334cdddda6df521a9cad54d327491feb` |

The maintained suite passed 19 tests. It verified the accepted full provider specimen and synthetic mismatch at 114 counted reads, and terminal `BUDGET_EXHAUSTED` at 113 or one. The independent mini replay verified one synthetic posting per employer against the approved saved authority with ten counted reads. Limits of nine and one returned `BUDGET_EXHAUSTED` with the exact count and no evidence. The count includes the saved configured response, two employers, one alias, and actual replay transport reads. An already-expired run produced `TIMEOUT`, and an overlong proposed deadline held. Stale pending and raw configured bytes, conflicting tenant slugs, mismatched Company row, and prebuilt proof fields all held or changed without positive evidence.

Real-process QA proved that the worker read standard input from `/dev/null` while the supervisor retained a private caller-provided descriptor. Reversing just that launch option and its line wrap reproduces the earlier reviewed source hash. The supervisor stopped and reaped the paused worker at the absolute deadline. A process cut after the durable reservation yielded an interrupted hold before expiry and a timeout after expiry, both reusable unchanged with no second replay. A finished positive receipt returned exactly the prior bytes after cutoff even with switched evidence bytes. Advancing the pending generation during a reserved attempt returned `CHANGED_INPUT` with no evidence. Swapping the current private slot path to a byte-identical directory while the child was paused returned `CHANGED_INPUT`, and neither inode acquired a receipt. A competing held mutex was reported `BUSY`. Unowned worker invocation and inherited application lease were refused, and corrupted, impossible positive, or foreign-generation terminal records were refused without overwrite.

A successful new slot contained only its pinned input files, private verifier lock, reservation, and private receipt. No application state, job database, queue, qualification, repair task, outcome, or release artifact was created. The independent probes contacted no provider, service, or workbook. The private receipt checksum detects corruption inside the owned channel. A hostile same-UID writer or invented slot is outside its custody boundary, and the future local finisher must own and recheck current application authority. This report includes no raw corpus or captured response fields.

### Reproduction

From `/tmp/jsh-s5-ordinary-verifier.povmDDEm`:

```sh
sha256sum -c checkpoints/QA_SHA256SUMS
qa_tmp=$(mktemp -d /tmp/jsh-s5-verifier-independent-pytest.XXXXXXXX)
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o pythonpath=dev --basetemp "$qa_tmp/pytest" -q tests/test_ordinary_rippling_verifier.py
```

From this report's private directory:

```sh
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_ordinary_verify.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_ordinary_lifecycle.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_ordinary_active_races.py
```

The hash check, maintained suite, and all three independent runs exited 0. The 27 independent observations are retained in `independent-final-boundaries.log`, `independent-final-lifecycle.log`, and `independent-final-active-races.log`. The maintained run took 5.89 seconds and is preserved in `maintained-final-tests.log`.

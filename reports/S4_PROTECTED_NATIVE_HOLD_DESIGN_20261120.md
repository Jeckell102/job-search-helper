# Sprint 4 native protected-evidence hold: narrow diagnosis

2026-11-20. Independent source inspection and disposable SQLite experiment. No production data, service, capsule, archive or coordinator file was modified. No network calls or live lock operations were performed by this reviewer. No delivery/system error occurred.

## Result

**A separate ordinary read-only SQLite connection can reproduce the exact `database changed during read` hold by creating WAL artifacts while the witness is reading.** This was demonstrated using the exact approved archive's `protected_state.database`, `/usr/bin/python3 -I -B`, cwd `/`, and a disposable WAL-mode database. It changed no database rows. The same witness passed when repeated sequentially after the preview.

This proves a concrete mechanism, not attribution of the real installation failure. Root independently reported that the exact native archive reproduced this fixed reason during a separate read-only Jobs/workbook preview. Root's role-specific before/after metadata comparison must identify which real artifact changed before concluding that this was the cause of the original install refusal.

## Source and launch distinctions checked

The actual archive is:

`/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-listener/host-check`

SHA-256: `c70212dccd5791e0173949605e8bd54f4736a03e6c9bd6ef788c0f87363eaa6a`.

All **11 embedded executable Python modules** exactly match current `site-source` (including `host_check_main.py` mapped to `__main__.py`). No stale embedded-source difference was found.

- Archive shebang: `#!/usr/bin/python3 -I`. `controller.py:504-527` launches it from `/`, inherits the controller environment, adds `JSH_F3_HOST_PHASE`, and starts a child session.
- Native system interpreter measured here: Python **3.10.12**, SQLite **3.37.2**. The project venv is Python 3.11.18 with the same SQLite version, but root confirmed the passing direct reproduction already used `/usr/bin/python3 -I -B`; interpreter version therefore does **not** explain that contrast.
- Actual `host_check_main.py:22-32` checks the authenticated parent controller and its real release lease. The first reproduction used its own stable PID/owner callback. That is a concrete untested distinction in the first reproduction, but the newer exact-archive child test and its specific database error narrow attention away from it.
- Cwd alone is not implicated by this source: protected paths are absolute, and `launcher_witness.py:119,132` already forces its own child probes to `/`. Direct launcher errors go through the other generic exception summary; they do not themselves raise the reported protected-witness summary.

## Why a read-only preview can interfere

`site-source/protected_state.py:95-117` records database, WAL and rollback-journal identity/size/mtime/ctime before opening SQLite. With no nonempty WAL it uses `?mode=ro&immutable=1`; after the read it requires the exact original tuple. SHM must be an ordinary file if present, and broader physical continuity also tracks it. The final database comparison is intentionally stricter than equality of logical rows.

The actual production `src/job_search_helper/sqlite_repository.py:73-89` opens `readonly=True` with **`?mode=ro`**, then reads metadata/schema. It does not request `immutable=1`. SQLite database read-only mode does not guarantee no filesystem side effects in a writable WAL directory. Even adding `PRAGMA query_only=ON` does not suppress all WAL bookkeeping.

The disposable test began with a WAL-mode database after its writer had committed and closed, leaving no sidecars. While the exact witness's immutable read was open, an independent `mode=ro` reader selected the row and closed:

```text
baseline: database=8192 bytes; WAL absent; SHM absent; rollback journal absent
after read-only SELECT: WAL created; SHM created
after reader close: WAL=0 bytes; SHM=32768 bytes; database metadata unchanged
exact witness exit: HELD — database changed during read
sequential witness control: PASSED; all artifact metadata unchanged
```

The empty WAL's absent-to-present change alone satisfies the witness's exact failure condition. No concurrent row writer, schema change or changed job value is necessary. This experiment demonstrated **creation**, not deletion, of the WAL/SHM. It did not demonstrate that a read-only reader rewrites database pages or removes an existing WAL; do not infer either. Last-connection cleanup by other writable handles is a separate possible artifact transition that needs its own observation.

## Smallest disposable regression

Use the native system interpreter and the unmodified reviewed `database()` helper. No fixture services, workbook client or application imports are needed:

1. Create a temporary database, enable WAL, create/insert one sentinel row, commit and close the writer. Assert no WAL/SHM remains.
2. Capture stat tuples `(device, inode, size, mtime_ns, ctime_ns)` and existence for database/WAL/SHM/journal.
3. Enter `database(temp_path)` and read the sentinel. Inside that context open a second `sqlite3.connect(temp_path.as_uri() + '?mode=ro', uri=True)`, set query-only, SELECT the sentinel and close it.
4. Assert the sentinel is unchanged, empty WAL/SHM appeared, and witness exit raises exactly `WitnessHold('database changed during read')`.
5. After the preview closes, run the unmodified witness sequentially. Assert success and unchanged artifact tuples.
6. Control: use a second immutable read-only connection against the same deliberately quiescent, checkpointed fixture; assert no new sidecars and witness success. This is a fixture control, not permission to change the production reader to immutable against an active WAL database.

The first five steps were executed successfully in a `TemporaryDirectory`; the sixth is the proposed additional regression control. The temporary database was removed on exit. No durable probe source was added outside this report's ownership.

## Next native diagnostic and disposition

Run no other SQLite preview during the next witness comparison. Keep root's diagnostic limited to role labels and artifact existence/stat deltas; protected row values are unnecessary. Record independently whether the wrapper is active and bridge held, without silently changing those conditions between paired checks. Compare sequential preview-then-witness against the observed overlapping case before attributing the original failure.

If the role/artifact comparison confirms the preview caused the change, the smallest correction is **execution ordering**: finish and close read-only previews before establishing the protected checkpoint, then avoid opening another ordinary SQLite reader during that witness window. No witness criteria need changing. If a necessary background service changes artifacts despite the existing intended hold, diagnose that specific owner separately; this experiment does not establish its behavior.

Do not ignore empty-WAL transitions, exclude sidecars from the comparison, refresh the protected pin merely to hide a difference, remove sidecars, force checkpointing, or apply `immutable=1` blindly to live WAL data. Preserve the exact comparison and show the correct sequential/no-interference behavior instead.

# Five retained terminal plans — immutable production-shaped adapter check

## Result

The isolated adapter built an exact binding for all five completed retained
one-operation Companies plans from the live stores read-only and again from the verified immutable backup using SQLite
`mode=ro&immutable=1` plus `PRAGMA query_only=ON`:

| Company | State stage | Compact visible fields | Local-only fields | Result |
| --- | --- | ---: | ---: | --- |
| COMP-0002 | blocked | 4 | 4 | REMOTE_OBSERVED_MATCH (offline transport) |
| COMP-0008 | blocked | 4 | 4 | REMOTE_OBSERVED_MATCH (offline transport) |
| COMP-0016 | blocked | 4 | 4 | REMOTE_OBSERVED_MATCH (offline transport) |
| COMP-0040 | unsupported | 4 | 4 | REMOTE_OBSERVED_MATCH (offline transport) |
| COMP-0045 | unsupported | 4 | 4 | REMOTE_OBSERVED_MATCH (offline transport) |

Each retained operation had the legacy omitted `append_if_missing` flag (the
historic non-insert meaning), eight value fields, no expected values, and a
1/1 cursor.  The adapter now normalizes only that omitted flag to `false`; an
explicit insert or malformed flag remains refused.  It also no longer rejects
an unrelated confirmed receipt for another Company merely because it names the
same historical cycle.  A receipt for the selected Company still holds.

The disposable transport was constructed only from each frozen compact-visible
projection.  It implements exactly `read_columns` and `read_row`; `commit`
raises.  Each case made two offline reads, returned `REMOTE_OBSERVED_MATCH`,
and made no commit.  State, Jobs and Inbox main/WAL/journal device/inode/mode/
size/time snapshots matched before and after.

## Commands

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
  python3 -m unittest -v tests/test_exact_legacy_terminal_observation.py
# 5 passed in 0.496s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 production_shaped_terminal_observation.py /path/to/verified-backup/.state
# 5 immutable-store bindings/readbacks; stores_unchanged=true
```

All source/test/script paths are confined to
`/tmp/jsh-retained-continuation.uqzSOPbJ`.

## Exact limits

This is not a real Sheets observation: remote rows were disposable copies of
the frozen visible values, no Google client or credentials were created, and
the check cannot establish actual remote delivery.  It does not persist an
observation receipt, alter the original legacy plan/cursor, change State/Jobs/
Inbox, qualify a terminal hold, pause a cycle, clean up work, or authorize any
live action.  Durable journal integration and an independently guarded real
readback remain root-owned separate work.

[Verified backup rerun](S5_FIVE_TERMINAL_OBSERVATION_COPIED_RESULT_20261121.json)

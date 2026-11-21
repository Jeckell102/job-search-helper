# S6 exact local retry status corrective recheck

**ACCEPT for the staged read-only status route.** The corrected actual CLI passed the original physical regression. Against an idle clone with no SQLite support files, it reported `HELD_SOURCE` without creating or changing a file. While a normal writer held 16,512 bytes of committed, uncheckpointed Jobs WAL, the command returned `STATUS_SNAPSHOT_BUSY`. It gave the same hold with an open 4,616-byte State rollback journal. Every existing path, inode, mtime and SHA-256 matched before and after each status call, including the pending journal files. [Physical regression script](/tmp/jsh-s6-retry-status-recheck.fVX7VwTb/read_surface.py) · [Final physical result](/tmp/jsh-s6-retry-status-recheck.fVX7VwTb/read-surface-jzzhnts9/RESULT.json)

The real shell reported `WAITING_TO_SCRAPE` at the exact queued retry and `HELD_SOURCE` after the fixture Company URL changed. An unknown attempt exited 1 with no success JSON and the legacy `--local-only` output retained its visibility. A copied two-sided archival terminal fixture reported `SYNC_CONFIRMED`, then `CLOSEOUT_PENDING` after removing the Jobs acknowledgement in the copy. Logical database dumps and the exact queue and release records matched across status checks. [Normal shell canary](/tmp/jsh-s6-retry-status-recheck.fVX7VwTb/prove_status.py) · [Normal status results](/tmp/jsh-s6-retry-status-recheck.fVX7VwTb/actual-queued-company-sckhmo0e/RESULT.json)

The reviewed route requires ordinary main database files, refuses to report from a nonempty or nonregular WAL or rollback journal, and compares main file device, inode, size, mtime and ctime before and after all reads. Each immutable SQLite handle is explicitly opted in. Existing ordinary handle constructors retain their previous default mode. Physical proof disabled Python bytecode generation to isolate data-directory effects. Fixtures and subprocesses were private and offline. [Original HOLD retained](/tmp/jsh-s6-retry-status-independent.IjAUKZdD/INDEPENDENT_QA.md)

| Artifact | SHA-256 |
| --- | --- |
| repair_retry_status.py | `ef5e8d51490e073de119fca876e5cc85ffb6418961f3daf97b36191e041b5290` |
| runner.py | `0b4e80b429b242a1eec02eadb5b89ac501b8d13f7dc0c3122015e01eece91003` |
| engine.py | `1c466d8c33d1dbd102325eee8b7d834667024ad9f20d119a4efab019fc3424f8` |
| inbox.py | `dc6f207088e755ac98bd6541ed1ec1b608dc81b2359b7c908883eeb81e43dee1` |
| sqlite_repository.py | `3ab772748e685a131f885c0eefa7bd8055ed5c22114d4f89204a6dce3d8ff742` |
| Actual shell proof | `6e97403bc5febad379ba66ad61ca1719e58feb7866e6ae1b0ba5d8d31d877195` |
| Actual shell result | `dd47be548d594e51b5c82e70e675fec425b1824ced439714a9a6945391db2d2c` |
| Physical regression script | `752d0a650a38a76d5d126282bd250502a47e0f5d7026a17573b09bb6a0e61aa4` |

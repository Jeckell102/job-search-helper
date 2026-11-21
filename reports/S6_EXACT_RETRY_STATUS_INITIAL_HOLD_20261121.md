# S6 exact local retry status independent QA

**HOLD for the filesystem read-only requirement.** The actual `company-queue-status --attempt-id` command against an idle disposable WAL-mode store set created six SQLite sidecar files, one `-wal` and one `-shm` for each of State, Jobs and Inbox. All prior files retained their inode, mtime and digest. This reproduces even with Python bytecode generation disabled and no other process using the clone. Existing application protected-state verification treats new sidecars as a continuity change. A normal status check must preserve the protected store paths if the route is to be accepted as filesystem read-only. [Sidecar reproduction](/tmp/jsh-s6-retry-status-independent.IjAUKZdD/read_surface.py:27) · [Exact observed paths](/tmp/jsh-s6-retry-status-independent.IjAUKZdD/read-surface-lvl21ls3/RESULT.json)

**Status semantics passed.** The actual launcher reported `WAITING_TO_SCRAPE` for a canonically queued attempt, then `HELD_SOURCE` after its fixture Company URL changed. An unknown canonical attempt ID exited 1 with no success JSON. Existing `company-queue-status --local-only` kept its previous JSON visibility. An archived, two-sided completed retry reported `SYNC_CONFIRMED`. Removing Jobs acknowledgement rows in a separate disposable copy produced `CLOSEOUT_PENDING`. State, Jobs and Inbox logical dumps matched their immediate pre-command snapshots for all probes. No remote calls or durable database writes were observed from the command. [Actual shell fixture](/tmp/jsh-s6-retry-status-independent.IjAUKZdD/prove_status.py:181) · [Status results](/tmp/jsh-s6-retry-status-independent.IjAUKZdD/actual-queued-company-_qzqbgq_/RESULT.json)

The code uses SQLite read-only handles, which protect the database against SQL writes while allowing WAL cooperation files. A repair needs a coherent current-read boundary for open or nonempty WALs as well as the idle zero-WAL case used here. An unconditional immutable SQLite URI can ignore mutable journal evidence. All runtime calls and changes were contained in disposable paths. No production, provider, network or model access occurred.

| Artifact | SHA-256 |
| --- | --- |
| repair_retry_status.py | `1d3974a21d4ee0687906b713c7347ae1fff5db36a3144fc076fb6b8e60953eb3` |
| runner.py | `0b4e80b429b242a1eec02eadb5b89ac501b8d13f7dc0c3122015e01eece91003` |
| job-search-scraper | `2556de3371c32be1991273a1ee88d2baa25753dfcdc73a9656d34de6b91de78c` |
| Actual status fixture | `c7e11316b9b4497b2650ec650073bc281093a2c97eda4042a26d3e56845cb448` |
| Status result | `0c585333e161ed5c8d4b8bf66c62d51d518e1c498d1370e1a7e77d9707fb23a3` |
| Sidecar reproduction | `81e1616f83e0597d109d5be44e269f6e57eb3ad1ae02986bf927f0fdad4428bf` |
| Sidecar result | `333880f771d8f8f1c55e119510118b32fd711353fe6eac957df71114969debfe` |

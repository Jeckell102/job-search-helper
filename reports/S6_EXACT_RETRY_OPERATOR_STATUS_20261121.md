# Sprint 6 exact retry status

Use `./job-search-scraper company-queue-status --attempt-id RTRY-…` in the
staged candidate to inspect one attempt. It reads the exact queued request,
current Company source, release and retry ownership, and matching Jobs and
Inbox evidence. It reports the current hold or next stage without requesting
work, changing a record, or calling a provider or Google Sheets. The existing
`--local-only` queue output remains available.

`WAITING_TO_SCRAPE` means the qualified retry is still queued.
`HELD_SOURCE` means the approved source revision has changed. Other holds
identify missing or incomplete ownership and evidence. A local inventory
application and its matching verified Inbox plan can report pending Sheets
confirmation. `SYNC_CONFIRMED` requires matching terminal evidence in Jobs
and Inbox. A missing terminal receipt leaves closeout pending.

The original implementation opened read-only SQLite handles that could
create WAL support files. The corrected command reads immutable snapshots
only when the three stores can be read without pending WAL frames or a
rollback journal. If a journal is nonempty or a database changes during the
read, `STATUS_SNAPSHOT_BUSY` asks the operator to try again after writes
settle. The ordinary application handles retain their prior behavior.

Four status tests and 30 existing admission, Inbox, launcher and owner tests
passed offline. Independent QA repeated the physical-file regression through
the measured shell, with real WAL and rollback journals and both terminal
receipt dispositions. The command passed on the corrected staged source.
The command has yet to be installed in production.

[Initial QA hold](S6_EXACT_RETRY_STATUS_INITIAL_HOLD_20261121.md)
· [Independent recheck](S6_EXACT_RETRY_STATUS_INDEPENDENT_QA_20261121.md).

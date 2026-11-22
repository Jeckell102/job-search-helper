# Staged fix for Companies added only in Sheets

November 22, 2026, Eastern. The first manual Start can discover an
eligible Company row still only in the workbook and pass it to the
existing scoped scrape. The fix targets the
[measured startup gap](S7_MANUAL_INTAKE_RECHECK_20261122.md).

For an initialized compact workbook, the launcher performs a read-only
Companies discovery when no local event or request owns Start. It picks
one active addition with a stable ID and unambiguous current and historical
name ownership. It keeps the established full-scan entry when the read
finds no eligible addition. The initial read preserves interactive
credential recovery. Under the existing scraper and writer leases, it
rereads the exact row and atomically inserts that Company and its outbox
event before calling the existing scoped route. A different queued
request or a changed row prevents import. Discovery never writes to
the workbook. Existing automatic controls are untouched.

The [initial independent hold](S7_EXTERNAL_FIRST_START_QA_HOLD_20261122.md)
found name ownership, status and credential recovery gaps. The amended
source checks historical aliases during discovery and the insert
transaction, rejects duplicate remote names and requires the normal
admission command's explicit Active status. Existing paused Companies,
blank or inconsistent identities and unresolved multiple additions are
handled before scope begins.

Eleven tests used the real copied launcher, private stores, a provider
fixture and a workbook fixture. One still-external row produced one
Company event and a measured scoped job result, which reached
`SYNC_CONFIRMED` on the first invocation. One local Job History record
and one full-description evidence record were saved. The workbook
fixture confirmed the same Job Key in one batch. The zero-job case,
idle/busy local paths, regular no-addition workflow and specific hold
conditions passed. The fall-through test confirmed the original
admission descriptor remained valid. Three existing focused checks
passed for the legacy fallback, backend drift and uncertain write
recovery without re-fetch. [Pinned scope and results](S7_EXTERNAL_FIRST_START_STAGED_20261122.json).

Independent QA accepted the amended staged source. The reviewer verified
the three changed source files, the unchanged launcher and bootstrap,
all 11 projected source trees, the successful case's one exact saved
job and fixture write, and the hold cases' zero events and fetches.

The exact source change affects the manual selector, runner and
SQLite Company import. The current candidate SHA-256 is
`6790d8b388045ef6b32736944c6f78007ff158099d574d66e982825ab749cde5`.
The patch checks cleanly against the current installed source. Test
and source evidence remain under `/tmp/jsh-s7-external-first-start.yi_zfodl`. Final release preparation
and a genuine Sheets-only addition through the deployed path remain
open. No production deployment, provider or Jetson call or live job
or workbook write was performed.

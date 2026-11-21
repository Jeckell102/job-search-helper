# Sprint 6 maintained coordinator reliability baseline

November 21, 2026, 01:54 Eastern. Ran the maintained coordinator tests in a
clean disposable copy of the reviewed promoted-repair coordinator and the
stage that completed the Amphenol test workbook. Network connections and
address resolution were denied. No services, production data, workbook,
provider, or Jetson requests were used.

**103 passed, zero skipped, in 14.45 seconds.** The seven suites exercise
inference reservations, campaign completion and isolation, coordinator
recovery, current repair profiles, retry history, and supervision. Existing
checks cover stale results after a pause, exhaustion moving the campaign to
the next eligible task, unresolved inference holding the lane, disk
pressure, and shutdown with work active. The copy's test and coordinator
source digests are in
`/tmp/jsh-s6-maintained-reliability.341x2k25/source-pins.json`, SHA-256
`f569320882d3b5c671ba6d701766b7c2e6b013c7bf23bd8ecfa17415bd6d6ae0`.

This is a source baseline for the sequential acceptance work. The composed
production version, three different unfinished qualified companies, and
actual event-to-storage progression are still open.

The scoped retry also has a separate local closeout test for reuse in the
sequential proof. See [Amphenol publication and local closeout](S5_AMPHENOL_FIXTURE_WORKBOOK_PASS_20261121.md).

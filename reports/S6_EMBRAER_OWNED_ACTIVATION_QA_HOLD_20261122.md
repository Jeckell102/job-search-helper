# Embraer owned activation review

November 22, 2026. Independent QA rejected first activation for a concrete
restart gap. The application-side typed partial, exact local settlement,
and no-publication boundary passed scoped review.

The reviewed coordinator could durably promote one held repair to
`PAUSED` and stop before `pilot-start`. On restart it treated the still
pristine promotion as already prepared and never queued it. This is a
safe hold with no duplicate inference, but leaves an enrolled automatic
repair stranded. A deliberately paused task must still stay paused.

Required repair owners and proof:

- The coordinator lane owns detection and recovery of the exact pristine
  pre-activation task. A fault inserted between the durable promotion and
  first activation must resume once. An explicit pause in the same interval
  must stay held. Existing successful replay must not resume or create a
  second task.
- Root's production readback found that both shared wrapper working copies
  contain older parser and dispatcher bytes. The same coordinator lane
  owns an Embraer-only source baseline pinned by its full file digest.
  Existing shared baselines keep their own source and roles.
- Independent QA owns retesting those two changes before package approval.
  Reuse the real fixture that joins parser, application settlement, paired
  delivery and one isolated development task.

The first application composition used real disposable SQLite stores and
a workbook fixture. The new shell command passed the stable pre-import
lock and canonical path checks on the project Python 3.11. A separate
QA run with Python 3.10 cannot run the existing bootstrap's `-P` option.
Two existing bootstrap suite expectations also failed on the unchanged
production baseline: inherited synthetic runtime digests and a missing
terminal receipt. These failures did not create or expose a new release.

No production files, jobs, Sheets, services, or Jetson inference were
changed. The staged reference parser remains separate from the trigger.

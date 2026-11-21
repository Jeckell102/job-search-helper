# Scoped repair retry admission and terminal delivery

November 21, 2026. Independent QA accepted both changes on staged source.
The source and validation are at
`/tmp/jsh-s5-confirmed-retry-outcome.20261121`.

The previous bridge recreated a consumed retry. A normal `requested_scan`
fixture preserved its durable State and consumed the queue file. The old
bridge wrote the same request again. The replacement returns
`REQUEST_ALREADY_ADMITTED` for the exact accepted request and leaves the
queue empty. It checks the saved canonical request, installed runtime, sole
Company, and complete intake measurement. Conflicting evidence stays held.
[Initial rejection](S5_RETRY_ADMISSION_REPLAY_INITIAL_QA_20261121.md).
[Independent retest](S5_RETRY_ADMISSION_REPLAY_RECHECK_20261121.md).

The previous outcome recorder accepted a global storage assertion for the
repair retry even after the linked Jobs acknowledgement was removed from a
disposable copy. The replacement waits for the retry's closed State
checkpoint, matching confirmed Inbox receipt, and verified Jobs acknowledgement
in the corresponding application stores. It ignores unrelated pending cells
when those exact proofs agree. The generic writer cannot supply a completed
retry through a different request, Company, or disconnected database.
[Initial rejection](S5_RETRY_TERMINAL_INITIAL_QA_20261121.md).
[First recheck](S5_RETRY_TERMINAL_FIRST_RECHECK_20261121.md).
[Final independent pass](S5_RETRY_TERMINAL_FINAL_RECHECK_20261121.md).

An offline replay copied only the disposable Amphenol closeout fixture.
Removing the Jobs acknowledgement, downgrading the Inbox receipt to pending,
or replacing the State fingerprint withheld success. Restoring the exact
evidence recorded one immutable `COMPLETE`. The maintained two-sided
delivery produced a single receiver `VALIDATED_COMPLETE` event, and replay
left that event unchanged. The fixture source inventory and workbook rows
had already been tested separately. No native stores or providers were
opened by this replay. [Fixture publication](S5_AMPHENOL_FIXTURE_WORKBOOK_PASS_20261121.md).

The comparative offline sweep had 57 passes and 24 failures on the earlier
composed source. The repaired source had 69 passes with the same 24 failing
legacy tests, plus both independently accepted targeted suites. The old
failed cases used earlier runtime or fixture contracts, including absent
activation journals and missing methods on exact-recovery mocks. Their
unchanged failures remain visible in the local baseline and composed logs.
These staged results leave the live release and whole-sprint exit gate open.

The next integration task is a single maintained owner handoff from the
promoted candidate and independently pinned release qualification through
existing safe retry dispatch and exact publication to this terminal result.
The source already contains the measured release entry point. The current
standalone rehearsal is its only caller. Use an explicit owned request
throughout, with no generic start fallback when the retry queue has emptied.

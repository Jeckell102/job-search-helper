# Sprint 7 queued Company scope recheck

November 22, 2026, Eastern. The actual launcher, bootstrap, and runner changed
since [the earlier source-drift check](S6_MEASURED_QUEUED_SOURCE_DRIFT_QA_20261121.md).
The previous harness was applied to a copy of the current installed source
matching release `REL-d37d7d64a0fd3788e02e699f` and source digest
`5433ca39278030cc7c77bc30ae8e9d6431df57b4eb9cfa6a82be6fcea0a188d5`. It ran a real child process of
the measured launcher for each of two disposable Company attempts.

| Scope change after retry enqueue | Result |
|---|---|
| Active Company's source URL changed | The new source revision differed. The child stopped before admission. |
| Active Company became Paused | The source authority returned no eligible revision. The child stopped before admission. |

Both cases exited once with the same stale-retry hold. The queue bytes,
release and retry records, and State, Jobs, and Inbox logical snapshots
matched their before-worker values. Admission, provider, and publication
calls were zero. The source copy still held the exact disposable candidate
installed at enqueue and the network guard was active.

The second check used the same qualified release owner before installation.
The input changed just before the real admission lock, after the earlier
source revision check. For both source change and pause, the locked
recheck refused activation. The installed source and post-edit stores
matched the originals. No release record, journal, retry intent, queue
or worker launch occurred. The existing preinstall unit test also passed
against the copied installed source.
[Receipt and version pins](S7_QUEUED_COMPANY_SCOPE_RECHECK_20261122.json).

Independent QA accepted both disposable boundaries. The reviewer
remeasured the source and worker trees, checked the actual lock path and
the two unchanged queue receipts, and confirmed the absence of release,
retry and worker artifacts in both preinstall cases. The two retry
children returned the same hold without any named effects.

Final deployed QA must bind these scoped checks to the final installed
version. These exercises used private stores and fixture qualification.
Production source, processes, job records, workbook and Jetson were
untouched.

For a recheck, copy the exact pinned source into the harness directory as
`installed-source-only`. Include `src`, `job-search-scraper`,
`release_admission_bootstrap.py`, and the two title lists. Run the harness
once for `source` and once for `pause`, first without and then with
`before-install`. The original trial path is
`/tmp/jsh-s7-scope-recheck.2uurzfc0`.

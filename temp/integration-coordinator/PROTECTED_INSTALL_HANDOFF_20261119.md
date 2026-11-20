# Protected installation handoff — 2026-11-19

Status: **APPROVED AND INSTALLED; PROJECT NOT COMPLETE**.

The accepted retained-work source was merged into this code/tests-only snapshot
of the current protected tree. Broader compatibility passed 281/281 and
independent focused QA passed 135/135.

The real checkout is heavily modified. Every existing target file matched this
reviewed snapshot immediately before installation planning. Exact rollback
copies, the target-file list, and the clean patch are stored at:

`/tmp/job-search-helper-protected-backup-20261119-2135`

Patch SHA-256:
`18e49304bc02b21c1f0009a2786c160f5816923b255fd95d33efe45c8c552832`

The earlier attempted protected apply was rejected by the approval gate and
made no change. The user subsequently approved the protected-tree install.
All ten pre-existing target files were rechecked byte-for-byte against the
saved rollback copies, `git apply --check` passed, and the exact patch above
was applied to `/home/chris/job-search-helper_old`. Protected focused
verification then passed 127/127 checks; the only warning was an optional
pytest cache write refused by the restricted filesystem. No live Sheet,
scrape, FIRST PASS, service, lock, or Jetson action occurred.

The completion re-audit found that the retained orchestration entry point is
not called by production code and that no enabled service automatically starts
the normal durable Company-only request. Those are open release questions; the
installation is not final roadmap acceptance.

Verified GitHub backup branch:
`backup/integration-automation-20261119`.

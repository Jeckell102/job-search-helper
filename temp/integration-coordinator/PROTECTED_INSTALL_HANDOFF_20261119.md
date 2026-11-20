# Protected installation handoff — 2026-11-19

Status: **PAUSED FOR EXPLICIT PROTECTED-TREE APPROVAL; NOT INSTALLED**.

The accepted retained-work source was merged into this code/tests-only snapshot
of the current protected tree. Broader compatibility passed 281/281 and
independent focused QA passed 135/135.

The real checkout is heavily modified. Every existing target file matched this
reviewed snapshot immediately before installation planning. Exact rollback
copies, the target-file list, and the clean patch are stored at:

`/tmp/job-search-helper-protected-backup-20261119-2135`

Patch SHA-256:
`18e49304bc02b21c1f0009a2786c160f5816923b255fd95d33efe45c8c552832`

The attempted protected apply was rejected by the approval gate and made no
change. Do not bypass it. Obtain explicit user approval to modify
`/home/chris/job-search-helper_old` despite its existing uncommitted changes,
then recheck hashes and apply only this patch. Run protected tests before any
live Sheet or company action.

Verified GitHub backup branch:
`backup/integration-automation-20261119`.

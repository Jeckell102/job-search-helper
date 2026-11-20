# Sprint 1 backup restore proof

Private branch `backup/integration-automation-m1-operator-20261120` was pushed and independently resolved to commit `079aea72193d8b6fffe45bf8cc31473053c74d5f`. The authenticated remote was the user's Job Search Helper repository.

The release owner reconstructed both versions of all 13 deployment files in a new disposable directory directly from the Git objects at that commit. The before files came from `tests/fixtures/f3-before/`; the after files came from the commit's project root. The backup's installer verified each version's SHA-256. The reconstruction applied each file's original permission bits from the installer's BEFORE and AFTER manifests because Git records only the executable bit. A plain clone alone does not reproduce all original POSIX modes.

The installer, gate and their tests were also read directly from the same commit. With `JSH_S1_BASE` and `JSH_S1_CANDIDATE` pointing to the reconstructed inputs, all 16 tests passed in 26.129 seconds on the project's Python 3.11. The original local fixture paths were not used by that run. This verifies recovery of the exact scoped inputs from the backup. It does not establish production deployment or replace independent installed QA.

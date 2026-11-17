# Coordinator QA repair plan

The coordinator assigns three independent repair workers and reviews their combined result.

| Owner | Scope | Acceptance |
| --- | --- | --- |
| Authorization worker | F1: explicit task modes and no-write constraints; host and Jetson command interfaces | Default review; development requires an explicit flag; no-write instructions cannot authorize edits |
| Recovery and budgets worker | F2 and F4: resilient scheduler, health reporting, token reservations, deadlines | Export errors do not silently kill the worker; unusable storage triggers supervised recovery; limits checked before dispatch |
| Evidence and progress worker | F3 and F5: task-specific evidence and stable progress comparisons | Required source/test reads and target source retrieval; a timing-only change cannot reset no-progress count |
| Coordinator | Integration, adversarial review, deployment, real workflow check, GitHub backup | Original coverage retained, six QA reproductions corrected, installed hashes verified, sanitized backup read back |

All development artifacts and test results will be retained under Job Search Helper's `dev/wrapper-coder/` on MuleLab. The Jetson retains inference and command forwarding only. Repair workers do not restart services or install their own changes. The coordinator installs after tests and preserves exact rollback copies. Existing scraper data and company wrappers are outside this repair scope.

The first QA assessment remains historical evidence of the pre-repair revision. Repair verification will be saved separately, with failures and incomplete live checks identified explicitly.

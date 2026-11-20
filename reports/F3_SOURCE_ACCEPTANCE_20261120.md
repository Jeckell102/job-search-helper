# F3 source acceptance

2026-11-20. Independent architecture QA accepted the frozen source candidate
at `/tmp/jsh-f3-resume.ErTFRd`. The SHA-256 of the scoped file manifest for
the reviewed candidate is `954453ee90926771905f8f6b8cf84646d0ac2353c4dee69c6fd72d8695a45a0c`.

## Evidence

- Coordinator combined run: 321 passed. The suite includes the other task's
  temporary retry, company intake, outcome delivery, and outcomes tests.
- Additional relevant groups: 179 passed for Engine, scopes, retained work,
  exact recovery, and SQLite integration. A separate backend-matched run
  passed 252 intake and exact-recovery tests before the final narrow policy
  repair. The groups overlap and must not be added as a unique test count.
- Independent final review: 225 focused regression cases passed. Additional
  fixture checks passed six of six shared policy cases and three of three
  direct Engine entry-point cases.
- Four subprocess activation and crash tests verified coherent startup before
  and after activation and safe recovery at the recorded journal boundaries.
  Public controller handoff and exact admission were exercised in subprocesses.
  A separate fixture confirmed one selected frozen plan through the public
  sync dispatcher using SQLite and a memory-only workbook, preserving the
  unselected company.
- Named sync now uses the same runtime policy as ordinary sync before opening
  writable state or constructing a remote client. Pre-upgrade unpinned work
  stays eligible only in the no-release sync-only compatibility path and only
  without a repair retry. The prior QA rejection is preserved separately.

## Concurrent work and production state

The separate task `Implement integration automation` was idle after the user
paused it. Production's seven temporary-retry source modules and its test
matched local commit `37512dd` byte for byte. The Sprint 1 candidate preserves
that install. The later rejected supervisor changes remain isolated. Direct
read-only inspection found intake, retained intake and temporary retry off.
The Samtec request remains present and explicitly scoped to `COMP-0739`.

## Scope and next gate

This acceptance applies to source and fixture behavior. Production installation
and verification are still open. The exact-plan success test used a simulated
workbook. No live scrape, release, Sheets change, Jetson action, service change,
or job data operation is authorized by this source verdict alone. Reverify
production base hashes, control settings, the retained historical boundary,
guards and rollback before any installation, and obtain independent deployed
QA at the applicable roadmap gate.

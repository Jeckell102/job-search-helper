# Promoted repair isolation — source-only slice, 2026-11-21

The existing qualified-repair promotion path created a paused task without
`isolated_workspace`, while the existing `pilot-start` admission requires that
flag. A reviewed profile cannot supply it through the assignment grammar.
Promotion also overwrote the existing source-only assignment baseline with
the shared checkout baseline, which does not match the isolated workspace
source when a separate queue baseline exists.

The fix changes only `coordinator_store.py`: promoted repairs now use the
existing isolated-workspace flag and retain `new_state`'s batch-source
baseline. Promotion remains paused and duplicate promotion returns the prior
task. Existing identity, source revision, file/test limits, budget and pilot
admission checks remain in place. No profile, scheduler, command, capability
or release behavior was added. Existing already-promoted task rows are not
silently migrated or recreated.

## Source and test evidence

- Stage: `/tmp/jsh-s5-promoted-repair-isolation.jzhc_e8c`.
- Full wrapper baseline: `/tmp/jsh-s4-receipt-candidate.i8gYgB0N`, with exact
  source overlay from `/tmp/jsh-s4-successor-release-payload.RBtyVLix/candidate`.
  The unchanged coordinator SHA is
  `b9fe2de378bcf942e1a7123e3d3e727ec97c41c803703ef6a2bae982a6a74175`.
  Application dependencies are a disposable source copy; no live store is used.
- New regression failed on the original source at the missing isolation flag.
  After the fix, it creates a canonical qualified-repair fixture, promotes it,
  confirms paused duplicate-safe admission, then uses the actual existing
  `pilot-start` and workspace preparation against distinct shared and queue
  sources. The private workspace receives the frozen queue source; the shared
  source stays unchanged. Repair identity, scope, tests and baseline are exact.
- No worker is started. There are no inference or action receipts. The single
  pilot is queued only in disposable storage; global queue, campaign and
  autopilot remain disabled. Git/test execution inside the inherited fixture
  is stubbed; workspace copying and admission are real application functions.
- **84 tests passed in 12.293 seconds**: `test_outcome_intake`,
  `test_coordinator_queue`, `test_coordinator_repair_profiles`. This includes
  unsupported-profile holds, duplicate handling, stale identity and queue/pilot
  regressions. System Python 3.11; bytecode disabled; socket connect,
  connect_ex, create_connection and getaddrinfo replaced with rejecting guards.
- No production source/state/service, controller, Jetson, network, profile
  enrollment or real generation launch was used. This is source acceptance
  evidence only, not deployment or generated-wrapper evidence.

Only two baseline files changed; exact before/after hashes are in
`CHANGED_FILES.json`, the complete source provenance is in `BASELINE.json`,
and the minimal transplant is `changes.patch`.

| File | SHA-256 after change |
| --- | --- |
| `dev/wrapper-coder/tools/coordinator_store.py` | `4b1f8d14a7cfb4dbd558a59b4b476567737a4983b785e244a9acdc64552989e9` |
| `dev/wrapper-coder/tools/test_outcome_intake.py` | `2cede57547a9d4bee464a5a83d14cd9fe8edae0cdb1bf44be5d3fe402cf33946` |

Root owns integration and any actual bounded generation attempt. A fresh
genuine failed Company and a reviewed bounded assignment remain required;
this slice does not invent a qualified profile or recast a working integration.

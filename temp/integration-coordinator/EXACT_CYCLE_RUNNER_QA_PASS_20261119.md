# Exact-cycle runner integration — independent QA pass

Date: 2026-11-19

Accepted hashes:

- runner: `fbcc7c3ddc899c16799a3f8ea38394a65558db77f5a0c61d436d5568ba1210ba`
- runner tests: `c5fc581a722f89cd05c371cab9e41326a25cbf1b4ae9625f5ea2bfc7631d910a`
- recovery factory: `915465b3d4bad56a8c8d719ead18ae6c6cfa5107cd06bcf7811f93ac2bd14d00`

## Result

PASS for guarded activation, subject to the documented fresh production
preflight and scoped deployment manifest. No live command was run in this QA.

The public command requires `sync --cycle-id ID` plus one to five unique,
repeatable `--company-id ID` values. Empty, blank, duplicate, and over-bound
selections reject before environment loading, factory invocation, or remote
construction. A public cycle-only command passes an empty list, never `None`,
so it cannot reach the retained internal containment path.

The exact branch uses the accepted lock-owned lazy factory and returns before
the legacy runner lock and global path. Inside the recovery-owned real normal
lock it constructs the readonly local repository, State, inbox, profiled direct
remote repository, and Engine; all dependencies close before lock release.
Local preflight rejects missing/unknown Companies, blocked inventory, finished
cycles, and invalid State/plan combinations before release or remote access.
An independent unsettled-release probe recorded one release check and zero
remote, Engine, or outer-lock calls, with local cleanup completed.

Source and runtime review confirm the exact path does not enter global schema
validation, `run_scoped_sync`, closed-job cleanup, manual opportunity intake,
review lifecycle/export, outcome delivery, performance persistence, or a
global fallback. The output reports the exact `planned`, `recovered`,
`confirmed`, `held`, and `skipped` lists. An empty-but-present frozen plan is
treated as present, matching the accepted recovery contract.

Independent verification passed 168 tests in 10.73 seconds; compilation and
`git diff --check` passed. Normal start and unnamed-sync regressions remained
green.

## Remaining activation gate

Before the first live action, save a scoped source/rollback manifest and rerun
the protected read-only production preflight for processes, locks, the exact
blocking cycle, inbox/plan counts, request file, and remote controls. Deploy
only the accepted files. The first live recovery selection remains one
explicitly named smallest existing planned Company; broad backlog processing
and the pause executor remain disabled until their separate gates pass.


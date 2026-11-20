# F3 independent source QA rejection

Reviewed the first frozen `/tmp/jsh-f3-resume.ErTFRd` candidate on 2026-11-20.
Verdict: **REJECT**. The independent reviewer ran 140 focused tests successfully
and verified the controller lock handoff, startup and activation ordering,
interrupted release/rollback recovery, and ordinary resume preflight.

The independently reproduced failure was specific to named exact sync. It
accepted an unpinned historical cycle in `COMPLETE` and `ROLLED_BACK`, while
ordinary sync held the same cycle. Both routes must share the pre-upgrade
compatibility rule. Allow an unpinned cycle only with `NO_RELEASE`, sync-only,
and no repair retry provenance. Do not assign a pin to old work.

The repair shares runtime-pin policy at exact read-only admission and the exact
execution boundary. Regression coverage must prove the three runtime states,
a repair retry missing its pin, matching and mismatched pins, and zero factory
calls on rejection. A separate fixture checks a real SQLite frozen plan against
a memory-only workbook through the public sync dispatcher. These remain
source-level checks with no production activation.

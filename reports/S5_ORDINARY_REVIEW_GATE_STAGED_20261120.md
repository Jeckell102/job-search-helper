# Sprint 5 ordinary handoff into FIRST PASS

Independent QA accepted the pinned disposable source in `/tmp/jsh-s5-ordinary-review-gate.O8PbCh9o`. The combined suite passed **440** with Python 3.11.18. Separate independent QA passed **32**, including both original independent reproductions. [Source checksums](S5_ORDINARY_REVIEW_GATE_SHA256SUMS_20261120.txt) · [Initial HOLD](S5_ORDINARY_REVIEW_GATE_INITIAL_QA_20261120.md) · [Independent acceptance](S5_ORDINARY_REVIEW_GATE_INDEPENDENT_RECHECK_20261120.md)

The controller now distinguishes two sources of readiness. A normal unenrolled cycle still uses the existing finished status and publication health. An enrolled scope needs one matching Jobs reservation, archived publication, and exact immutable outcome. The exact proof can authorize the enrolled review transition while the original generic cycle summary still reads In Progress. The controller preserves that original summary and does not run general storage preflight or sync for a confirmed enrolled result. It refuses a pending or malformed scope and compares the saved proof before and after the AI access checks.

The exact proof opens existing State, Jobs and Inbox through SQLite read-only handles. An earlier candidate changed State and Inbox file modes during readback. The repaired fixture verified every probe connection used `mode=ro` and preserved existing modes. A separate Python process invoked the same proof command on a disposable successful case and returned the matching terminal result.

The reviewed tests simulate the managed AI check and review entry. No live FIRST PASS run, production deployment, qualified positive repair outcome, or provider run occurred. Continue with the [owner-bound verification plan](S5_ORDINARY_POSITIVE_FINISHER_PLAN_20261120.md).

# Independent QA runtime clarification — 2026-11-21

While setting up the ordinary AcquireTM settlement review, I verified that
the unqualified `python3` executable on this host is `/usr/bin/python3`,
Python 3.10.12. My earlier source-only promoted-repair and typed-diagnostic
reports incorrectly labelled runs made with `python3` as Python 3.11.

The original test results and source hashes remain as recorded. The
promoted-repair 84-test result should be read as Python 3.10.12 evidence;
it was never a deployment or production-interpreter acceptance claim.

The exact accepted typed AcquireTM dependency was additionally rerun with
explicit `/usr/bin/python3.11` (3.11.18), `-I -S -B`, private source/test
paths and blocked network. All **60 tests passed in 0.985 seconds**: the 56
maintained cases and four independent probes. Source and fixture pins are
unchanged. Independent copy:
`/tmp/jsh-s5-acquiretm-typed-independent.c189s4w5`.

The new ordinary settlement review uses explicit Python 3.11.18 throughout
its final successful runs: 89 maintained plus three independent tests.
See `/tmp/jsh-s5-acquiretm-settlement-independent.kwxds9ct/INDEPENDENT_QA.md`.
Earlier reports are retained as historical evidence; this addendum corrects
their runtime label without changing their acceptance scope.

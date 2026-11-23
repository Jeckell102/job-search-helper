# Current release evidence for queued scope and settled restart custody

Measured November 22 Eastern against COMPLETE
`REL-4141919bb885000b0e7244c2`, source SHA-256
`2c9aecf5382fc6d17b749f978ae0950baf2259ffc9c088bcbf6b664305d8f588`.
The following checks use only the changed or previously unmeasured boundary.

## Demonstration 6 — queued Company change

The app launcher, bootstrap and main runner changed after the previously
accepted scope test. The same offline harness reproduced a Company URL
change and a Company pause after the retry was enqueued, using a
disposable copy of the installed source. Each case started one real
measured child process. Both children stopped before scan admission and
made zero provider or publication calls. Existing request, release,
intent and SQLite logical states stayed identical. The harness logic
is unchanged; only hashes for the installed source were advanced.

The preinstall proof remains the earlier independently accepted locked
recheck. Its qualified release owner, admission controller, release
engine, Company revision predicate and exact cycle receipt reader still
match. The SQLite repository change adds duplicate protection to
Company import. It does not change the current Company lookup used by
the locked recheck. No repeat preinstall exercise was needed.
[Earlier proof](S7_QUEUED_COMPANY_SCOPE_RECHECK_20261122.md).

## Demonstration 5 — settled work through a real restart

The classifier source installation stopped and restored the wrapper.
Activation separately verified a single wrapper restart at PID 803684.
A read-only comparison after both operations matched the complete
preinstall subsequences of 124 task rows, 295 tool receipts and 73
inference rows byte-for-byte using their recorded ordered digests. It
also verified the distinct first and second ATS tasks each retained
exactly one settled inference, with zero unresolved requests and zero
ATS retry publication. The first task remained terminal and the second
saved its own red verification. Broad queue, campaign and autopilot
remain disabled.

This advances current deployed custody for completed work. The
[in-flight lost-response proof](F4_PAIRED_DEPLOYED_QA_20261120.md) remains
a separate accepted cut. The final sequence and any current required
publication-interruption cut remain open. No new company, provider,
Jetson or workbook action occurred in these checks.

Evidence: the scoped results, proof readers and exact release record
are under `/tmp/jsh-s7-ats-final-scope/`,
`/tmp/jsh-s7-ats-restart-custody/` and
`/tmp/jsh-ats-classifier-release/`, respectively. Independent review
of these current-readback results follows.

Independent QA accepted both results within those limits and rehashed the
current launcher, runner, bootstrap, owner, controller, and application
journal. Use the first attempt's [terminal receipt](/tmp/jsh-ats-native-package/activation/INDEPENDENT_TERMINAL.json)
and the second attempt's [live partial receipt](/tmp/jsh-ats-classifier-release/activation/LIVE_PARTIAL.json)
to bind the request, cycle and outcome identities. The retrospective
custody check reads installed local records. It does not query Sheets.

# Sprint 4 pre-pilot rollback restoration

November 20, 2026. The alternate checkout restoration command now
supports a distinct pre-pilot rollback selection and approval. Its
private canonical selection uses schema
`sprint-4-pre-pilot-rollback-selection-v1` and `pilot: null`. It binds
the old runtime bootstrap, active workbook, real receiver path, exact
maintenance bundle and exact approved exchange policy. Use this route
only after the original joint controller verifies terminal
`ROLLED_BACK` under its normal retained leases.

The verifier reuses the protected-state witness and independently
approved state pin from the same hash-pinned site verifier used by the
joint controller. While holding the real scraper lease, it checks that
the protected live state still matches the pre-install baseline.
Both database file identities are checked across this read. This
ensures an unchanged protected application baseline, including pending
requests, event/outbox/receipt state, historical evidence and manual
protected fields. A created or partially executed pilot cannot use
this route. Changed data remains held for reconciliation by its
normal owner. Restore the alternate checkouts only with a separate
approved exact rollback observation, matching exchange identity and a
fresh protected-state reread. Recovery retains the original approved
evidence and does not imply acceptance of the new rollout.

The staged entry is under `/tmp/jsh-s4-rollback-restoration.lGqG60sR`.
Independent QA initially required an exact match to the original
controller's checker bytes and coverage of the retained FIRST PASS
tree. Both findings were fixed and independent recheck accepted
staged source. The updated site witness is in
`/tmp/jsh-s4-protected-first-pass.6wStPI2k`. It pins absent or complete
tree state and hashes the content of each retained FIRST PASS file.
The physical continuity check covers every bucket and nested file.
An earlier pin lacking that coverage is ineligible for rollback.

The combined rollback command and exchange suite passed 23 tests and
the revised site verifier passed 85. Fixtures use the real protected
baseline and actual exchanges on temporary paths. They reject proof
without the scraper lease, receipt source not bound by the original
controller, new outbox or FIRST PASS evidence, and installed release
through the rollback route. The separate isolated no-evidence hold
also passed during this checkpoint. No live release, company,
checkout, service or job data changed.

[Initial independent QA](S4_ROLLBACK_RESTORATION_INDEPENDENT_QA_20261120.md) ·
[Independent recheck](S4_ROLLBACK_RESTORATION_INDEPENDENT_RECHECK_20261120.md)

# Exact receipt request binding repair

This four-file source-and-test overlay repairs one fail-closed mismatch in the
v2 exact-cycle publisher. A normal scan receipt continues to use its immutable
`start_request_id`. Only v2 exact recovery explicitly derives its receipt with
the durable cycle ID already required by the exact remote journal.

The repair does not relax the journal's receipt equality guard, alter or delete
an earlier receipt, access Google, authorize a write, or broaden the selected
cycle/company. Installation must verify all four protected preimages under the
existing integration lock, retain a durable rollback copy, and verify all four
installed hashes.

Disposable tests passed 68 focused checks and 299 expanded checks with warnings
treated as errors. The new regression proves a cycle with a distinct
`start_request_id` preserves the legacy receipt default while v2 exact recovery
uses the cycle ID.

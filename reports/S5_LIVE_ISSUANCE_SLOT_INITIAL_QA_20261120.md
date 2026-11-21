# S5 live issuance slot independent QA

**REJECT.** An expired issuance can return current evidence after reopening, and a rollback that preserves the configured root inode can grant a second allowance for the same dispatch. Restrict use of this candidate to the disposable QA environment.

## Candidate and verification

- Source SHA-256 `0093000da8c035dcfcb17d915efb522ff5db96a62ddb4e9cdb5eb61a972432d2`.
- Bundled tests SHA-256 `fb7697af5453c52beb3521a59a5319e7f35c26980e41570d10ec0306b79425b8`.
- System Python, with the staged `src` on `PYTHONPATH), ran **58 bundled tests successfully**. They cover concurrent reservation, exact binding equality, input validation, ordinary process death at multiple points, recovery after a durable commit, and individual custody substitutions.
- Four independent disposable checks produced **three failed safety assertions and one confirming observation**. [Independent checks](/tmp/jsh-s5-slot-independent.6X8eSEDB/test_independent.py)
- The production checkout, its database, providers, Jetson, and GitHub were outside this review.

## Required fixes

### 1. Reject expired evidence consistently across writer and refresh

A writer can pass its elapsed-time check, cross the monotonic deadline while publishing the commit, and reject its own result as expired. The durable commit remains readable because refresh only validates the UNIX wall clock. An independent test held wall time constant and advanced elapsed time by 61 seconds before publishing a 60-second reservation's commit. The writer raised `RepositoryError` for expiration and a reopened channel returned the evidence. A separate check observed stale evidence become current again after a backward wall-clock correction. [Writer expiry](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:284) · [Final publication](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:307) · [Refresh expiry](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:219) · [Timing checks](/tmp/jsh-s5-slot-independent.6X8eSEDB/test_independent.py:33)

Persist a boot-scoped elapsed deadline in the frozen reservation and apply the same freshness rule before work, at durable publication, and during readback. Treat a changed boot identity as a hold unless elapsed-time validity can be established. If crossing the UNIX deadline independently triggers expiration, preserve that terminal decision across wall-clock corrections. Add the two timing checks to the release gate, including a fresh process after the commit boundary.

### 2. Preserve the dispatch spend across custody rollback

The same pinned root and the same dispatch could be reopened once all three per-dispatch names were moved away. The test kept the root inode and mode, then moved the committed slot directory and its two sibling records to a disposable sibling directory. The refreshed channel granted another allowance. A failed read taken between those operations would look like a dispatch that had never started. Normal process death and the bundled one-name substitution cases remained contained. [Reservation admission](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:170) · [Missing-slot readback](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:246) · [Rollback check](/tmp/jsh-s5-slot-independent.6X8eSEDB/test_independent.py:61)

Record the dispatch allowance as spent under the application owner's retained publication authority before yielding to work. Once that record exists, loss or restoration of the separate private evidence state must hold the dispatch. This authority needs to survive independent evidence-root rollback. Test a reopened process with the original root descriptor and inode after the entire dispatch namespace disappears.

### 3. Require application-owner authorization before treating slot evidence as accepted

A supported caller can construct the full binding from arbitrary syntactically valid digests, provide the matching tool digest and physical owner pin, commit synthetic digest strings, and read the record back. The pin checks protect a separately supplied owner configuration when one exists. The opener and binding API supply no independent authorization of a published dispatch, no proof that evidence was measured, and no usage counters for the declared budget. The module explicitly leaves application attestation and verdict approval with the owner and emits only a custody record. The synthetic test establishes that the custody record alone is insufficient to authorize a consumer decision. [Public opener](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:323) · [Binding fields and caps](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:131) · [Evidence check](/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/src/job_search_helper/ordinary_live_issuance_slot.py:266) · [Synthetic caller check](/tmp/jsh-s5-slot-independent.6X8eSEDB/test_independent.py:98)

At the owner entry point, derive dispatch and current binding from authenticated publication and current sources, keep the capability to create evidence private, enforce the request and byte limits at execution, and verify retained evidence before issuing a verdict. Gate the normal consumer entry point with a test that substitutes both syntactically valid fake digests and previously valid stale source pins. The test must show that neither yields an application verdict.

Under the candidate's stated ownership split, exact shape and equality of the frozen evidence binding are established. Freshness of the underlying publication, company and control revisions, candidate source, and evidence remains part of the owner integration. Acceptance of the owner integration requires its own verification.

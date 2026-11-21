# Sprint 4 manual Company publication recovery failure

November 21, 2026, 15:53 Eastern. Source candidate only. The existing
company-only publisher accepted a fixture workbook write whose response
was lost. Bare Start correctly returned `PUBLICATION_HELD` with
`uncertain_write`, but its output omitted the exact request digest. The
supported recovery command requires that digest and the exact cycle ID.

The focused interruption and lost-response tests returned one pass and
one failure. The latter failed with `KeyError: 'request_sha256'` when
checking recovery output from the actual runner (no live access). The
busy-boundary reviewer independently reported the same failure in the
combined suite. The prior helper is retained privately as
`/tmp/jsh-ordinary-start-gate-repro.20261121/candidate/manual_company_start_missing_scope.py`,
SHA-256 `8b9c0806968f40baa977d78fefe1f92899e1b7a558f2a74c0e8b02053e307b17`.

Root owns the correction. Return the already frozen request digest and
cycle ID with the existing publish result. Keep the existing admission,
publisher, readback, and durable receipt checks. Independent QA must
verify that exact continuation confirms the saved publication after one
provider fetch and without repeating the workbook write. No production
code, company records, or Google Sheets were changed by this test.

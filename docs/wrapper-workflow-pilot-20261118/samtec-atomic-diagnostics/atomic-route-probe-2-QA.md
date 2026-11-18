# Atomic route proposal2 independent QA

Result: **FAIL_BOUNDED_PROPOSAL**. Ten of12 offline routing cases passed; the2 required Samtec listing normalization cases failed. Nothing applied.

Exactly one code_edit, current SHA, unique old text and complete-file syntax all pass. Empty-path validation and both Samtec/other-employer detail parsing are restored. But the replacement still checks `host == 'samtec'` while host is `jobs.jobvite.com`; therefore `/samtec/jobs` and `/samtec/search` both remain normalized to `/samtec/jobs` rather than the required full search listing.

Rubric clarification: only the two specified Samtec listing inputs require the `/samtec/search` canonical board path. Valid Samtec detail parsing must retain its posting ID and other identity fields; its board path may remain jobs or become search. Other-employer detail behavior must remain unchanged. Evaluator updated accordingly; proposal1 still fails due to actual detail errors, not this clarified path expectation.

Source unchanged; isolated in-memory routing only, no wrapper installation or live integration claim. Full cases and response hash are in adjacent JSON.

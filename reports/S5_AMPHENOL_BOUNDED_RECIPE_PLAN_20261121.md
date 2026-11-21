# Proposed next experiment: bounded recipe selection

Recommendation: one evidence-backed configuration selection using the existing
4B model and single inference engine. Do not repeat the rejected free-form coding
loop or reset its counters. Preserve WRAP-9f416bbfab and its rejection as history.
This is a design recommendation only; no model/employer call or implementation
was performed here.

## What materially changes

The completed experiment failed at the Python/JavaScript execution boundary and
added an uncalled test helper. The next model output should be a small typed choice
among reviewed behavior, not executable Python/JavaScript. MuleLab owns the recipe,
validation, generated patch, tests, and provenance. This matches roadmap M4's
reviewed-provider-recipe level and the documented Samtec configuration precedent.

New inspected evidence is `/tmp/jsh-s5-amphenol-typed-live/result.json`, SHA-256
`d10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602`.
It records the same click on the exact board: old 25-ID fingerprint still present
at 98 ms, a different 14-ID fingerprint at 347 ms, advertised total 39, and
`acquiretm_updatepanel_premature_read`. Thus a permanent server-side page-repeat
diagnosis is not supported by this observation. The count 39 and timing 347 ms
must not become constants in a fix. The summary contains fingerprints rather than
raw ID sets, so independent disjointness/full-membership testing still needs its
captured page fixtures or equivalent raw-ID evidence.

## Smallest useful contract

1. Engineering authors and independent QA reviews ONE bounded AcquireTM
   delayed-listing-transition recipe before the acceptance run. Keep original
   employer/source, full-description, duplicate/total, page-cap, and stable-reread
   rules intact. The recipe waits for the intended listing transition using
   browser-visible state; it does not call the Python Page object in browser JS.
   A generic body change or arbitrary sleep is insufficient readiness evidence.
2. Freeze recipe version/hash, exact allowed source/config inputs, immutable
   acceptance fixtures, and support matrix. Bind scope to COMP-0490 and the exact
   existing board without making those writable model fields. The Samtec recipe
   is precedent for this workflow, not a reusable AcquireTM implementation.
3. Give the model a short evidence packet: typed receipt above, minimal old and
   final listing observations, the rejected callback error, and reviewed recipe
   capabilities. Require one strict JSON decision: recipe ID/version plus observed
   strategy/candidate ID and evidence reference, or `unsupported` with reason.
   A plausible alternative diagnosis/unsupported option must remain available;
   do not prefill the accepted choice and call it an AI decision.
4. Host validates identity, evidence hash/age, enum/schema, and source baseline;
   reject arbitrary code/selectors/URLs, unknown fields, unsupported evidence,
   or weakened safeguards. Compile the frozen reviewed recipe into a new isolated
   candidate only. Do not hand-edit per-company code after the model response to
   manufacture an accepted AI output.
5. Run original assertions plus independently collected delayed-transition
   regression, executable JS-boundary check, repeated/missing page negatives,
   and nonempty normal-dispatch/default-transport test. Then use the existing
   bounded live evaluator only after offline acceptance. No broad suite expansion
   is needed unless the generated patch touches shared helpers/routing.

## Budget and honest success claim

Use one bounded selection request with explicit cumulative accounting and durable
response/recipe/source hashes. Unsupported or malformed selection holds; any
successor needs materially new evidence/capability, not another blind prompt.
All existing 4B settings and the single inference lane remain unchanged.

Success means AI-selected evidence-backed configuration plus reviewed Python recipe
generation and subsequently verified normal-dispatch behavior. It does not establish
free-form wrapper coding, arbitrary unfamiliar-site support, or full roadmap
completion. Candidate validation, installation, company storage, synchronization,
and GitHub backup remain separate. A human-prepared recipe alone is not M4
qualification; the recorded AI decision and end-to-end evidence are still required.

References inspected: roadmap M4 lines 161-178;
`temp/pilot-repair-20261118/CONFIGURATION_RECIPE_OPTION.md`;
`SAMTEC_PILOT_ATTEMPT.md` and `SAMTEC_RESULT.md` as historical evidence;
the current guided failure report and exact typed public receipt.

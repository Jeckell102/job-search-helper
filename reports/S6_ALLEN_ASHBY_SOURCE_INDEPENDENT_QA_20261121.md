# Allen Control Systems source registry QA

**ACCEPT** the scoped registry correction.

- Candidate `company_sources.py` SHA-256 `8c7cbbb998be771dd8387b010af34afb32f88071baa71f3f459ad6b436ab7f80`
- Author `test_allen_control_source.py` SHA-256 `31683b2796bc50b99f9dcdb17b51ddf929f2e858077f310aba796089c1b2c492`
- Existing `ats.py` is byte-identical in baseline and candidate, SHA-256 `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e`

The only registry diff is COMP-0164. The existing match requires the Allen Control Systems name after case and whitespace normalization, and one of two exact registered URLs. Both the stored stale Greenhouse board and previously recognized official root resolve to `https://jobs.ashbyhq.com/allen-control-systems`. Other IDs and names, unrelated manually entered URLs, same-board path or query edits, the current official company page as an arbitrary stored URL, and direct use of the Ashby board retain their input source. The existing Ashby adapter retrieves the exact tenant and returns full descriptions.

The normal-dispatch fixture failed on baseline because the selected request still used the Greenhouse API. The candidate passed 17 offline tests across the authored fixture, five independent scope checks, and existing source registry and inventory validation regressions. The test runner used the isolated system Python 3.11 executable and denied sockets and child process execution.

The independently accepted public evidence identifies 19 full descriptions and matching exact board membership in `/tmp/jsh-s6-allen-source-qualification.3txefp33/PUBLIC_QUALIFICATION_REVIEW.md`. That evidence is public source qualification. This QA exercised only disposable synthetic fixtures, with no provider, Google, Jetson, or production effects.

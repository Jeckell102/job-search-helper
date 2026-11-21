# Independent separate-confirmation evaluator source review

ACCEPT the scoped evaluator source for one separately bounded fresh confirmation after the provider quiet period. This is preparation/source acceptance only; it is not a completed observation or current qualification pass. This lane executed no evaluator and made no provider call.

- `confirm_recipe_candidate.py`: `43ab6b9f3899b289992d95d9e79c6ff3c625fa7518cdb969bfda06fcc2a753a5`
- `PREPARED_CONFIRMATION.json`: `78a95e901880291ac54c8d0739818dd1cacc64c1d56dde18eb47b78ba8c82ada`
- Root: `/tmp/jsh-amphenol-current-validation.fehq8g9f`
- Original failed log unchanged: `dfd69d46fd48deeeab7feb88d457ba01978d5ef5d4ae4548adc076df5d41638e`

The exact diff changes only the loop from runs (1,2) to run (3,), replaces adjacent-run cohort equality with equality to the independently accepted prior complete cohort and normalized detail hashes, and emits a distinct terminal `separate_candidate_confirmation_passed` label. The source root, complete 256-member manifest (`7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea`), adapter/dispatcher pins, imported module paths, Company ID, board and provider remain fixed.

A static AST comparison proved the entire body of each normal-dispatch iteration identical to the original evaluator. Every requirement remains: complete dispatch; exact returned board/provider; complete initial and final listing; unchanged listing entries; stable advertised total and disjoint page IDs; exact full cohort; unique scoped URLs; observed unique JSON-LD detail identity and accepted employer; full normalized description equality/minimum length; and unchanged source. There is exactly one normal `fetch_inventory` call in the one-iteration loop. Existing bounded internal provider retries remain unchanged.

I independently derived from the original run1 `run_verified` record:

- Complete cohort: 39 unique jobs, digest `728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b`.
- Sorted normalized detail records digest: `dfc88fe9ea1383495535d8b1d8715f7e37f5df886f24fa4702dd17688d6cab71`.

Both match the new hardcoded confirmation assertions and prepared metadata. The detail digest covers each ID, URL, employer, normalized description length and normalized description hash. The 35-record blocked run has no run_verified entry and contributes neither comparison digest nor replacement data. The new evaluator never reads or writes the old log; it cannot retroactively change its failure. Its output must be saved to a distinct confirmation artifact by the owner.

Only a fresh complete run3 followed by both exact comparisons and the final `separate_candidate_confirmation_passed` record can establish the separate confirmation. A standalone run_verified record, partial result, changed cohort/detail, source drift or later exception is insufficient. This procedure would establish two complete matching observations (original complete run1 and fresh complete run3) while retaining the intervening blocked run2 as a failed attempt; it does not relabel the original two-run attempt successful. Storage, release, synchronization and retained-task recovery remain separate gates.

# Independent Freeform manifest gate for the consolidated scope

**HOLD for the exact 38-endpoint overlay through the accepted Freeform route.** A byte-identical copy of the actual Freeform `installer.py` accepted the original canonical 47-path manifest. The same `load_manifest` call rejected the canonical 38-path overlay with `Source path is outside the allowed scope: dev/wrapper-coder/tools/acquiretm_membership_recipe.py`. All 38 endpoint records have valid mode/digest shape and describe a change or addition. The manifest represents the frozen overlay's 28 replacements and 10 additions, using its exact before/after digests, modes and owners. [Frozen scope](/tmp/jsh-consolidated-scope.20261121/RESULT.json) · [Scratch manifest](/tmp/jsh-consolidated-installer-gate-independent.EMP9isny/consolidated_exact_38_manifest.json) · [Actual parser result](/tmp/jsh-consolidated-installer-gate-independent.EMP9isny/RESULT.json)

The installer pin comes from the latest accepted Freeform capsule, corroborated by the capsule's `SHA256SUMS` and exact Freeform restoration selection. The independent Freeform report pins the same 47-path manifest and terminal installer receipt. [Freeform terminal acceptance](/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S4_FREEFORM_TERMINAL_INSTALL_INDEPENDENT_20261120.md) · [Pinned installer](/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01/installer.py)

| Paths in the 38-endpoint overlay | Existing manifest rule |
| --- | --- |
| 26 flat `src/job_search_helper` Python modules, including four additions | Accepted by the path grammar. Package `__init__.py` is excluded. |
| `job-search-scraper` | Accepted by the named launcher grammar. The grammar also lists `job-search-helper` and `release_admission_bootstrap.py`. |
| `dev/wrapper-coder/tools/coordinator_store.py` and `host_server.py` | Both belong to the literal wrapper allowlist and have existing before-images. |
| Six new wrapper modules | Outside the allowlist. `acquiretm_membership_recipe.py`, `amphenol_candidate_release.py`, `amphenol_installed_verification.py`, `amphenol_recipe_candidate.py`, `amphenol_recipe_choice_input.py`, and `amphenol_retry_completion.py`. |
| Three changed wrapper modules | Outside the allowlist. `coordinator.py`, `coordinator_inference.py`, and `coordinator_supervision.py`. |

The existing parser also requires all three wrapper entries with present before-images. The third mandatory entry, `dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py`, is outside the frozen changed set. Its staged bytes and mode exactly match the accepted Freeform after-image, `efba3e77d3c4b9a9f85984ba345f58846309b301bc0b96aaad89b096e24c86ca` at `0664`. The exact parser rejects `before == after` records, so that unchanged endpoint is a separate manifest-contract mismatch from the nine rejected path names. [Exact parser checks](/tmp/jsh-consolidated-installer-gate-independent.EMP9isny/accepted_freeform_installer.py:95)

The reproduction copied immutable accepted metadata, called `load_manifest` under a read-only process audit guard, and inspected its literal path rules. No installer transaction, protected route, service, production store, network or live write was exercised. The accepted 47-path manifest was the only positive control. [Rerunnable parser proof](/tmp/jsh-consolidated-installer-gate-independent.EMP9isny/prove_manifest_gate.py:77)

| Artifact | SHA-256 |
| --- | --- |
| Frozen scope result | `09e871ceb0cc91685461294abef1651766cbebcb52b5655a63940fde74db13e3` |
| Accepted Freeform installer | `796e8b04cca48c7641c45480611ab43f2d19a2a96da9dc9a08d548d029fc1ee4` |
| Accepted original Control manifest | `a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163` |
| Canonical scratch 38-endpoint manifest | `c9e9a59c78e874703c9689f3ccab517a2fb0539da10896baf1a35979d0d8cd8b` |
| Independent parser reproduction | `e2294b6684f66624cddc82500b66e41dc2b379e1309a760b4b797edb810be65e` |
| Independent result | `6d611204beba19025a810a13a6039f55f74c8ea691004f36bae4d8a67051013c` |

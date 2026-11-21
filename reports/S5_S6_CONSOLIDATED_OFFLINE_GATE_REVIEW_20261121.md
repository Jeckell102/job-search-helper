# Current deployment payload closure — independent dependency audit

**One useful next offline gate: freeze and independently verify the exact current deployment payload against its accepted source pins and required runtime imports.** This is an F3 complete-version gate. It is not another live-readiness check or a rerun of the passing host/retry canary.

Current result: **the existing 31-endpoint inventory does not describe the current accepted host release chain.** This was already honestly noted in the deployment summary; the exact missing dependencies and changed pins below now make the necessary preparation concrete. Do not construct a new maintenance capsule from that old inventory as though it includes the later accepted behavior.

## Read-only evidence

Read the original F1–F8 ledger, current `S5_S6_DEPLOYMENT_SCOPE_AND_ACCEPTANCE_20261121.md`, current coordinator card, independent source-scope/host-release/typed-hold QA, and local Git objects for backup commit `fcd0f90f2a171a4693a418aa0e2e8ee455ffad70`. No remote Git request, application import/execution, native DB, service, provider, model, or Google operation occurred. Only this report was created.

The older `S5_NATIVE_SOURCE_SCOPE_20261121.json` is for `/tmp/jsh-s5-enrolled-retry-receipt.20261121`, observed 04:12:58 EST, with 31 endpoints. The deployment summary explicitly says the later owned host join and observation/status slices are outside that inventory.

The actual latest accepted host bytes, read from fcd0f90, directly import:

- line 322: `amphenol_candidate_release.read_owned_candidate_release`;
- line 342: `amphenol_installed_verification.verify_installed_amphenol_recipe`;
- line 344: `qualified_release_owner.UnfinishedScrapeWork` and `release_and_continue_qualified`.

| Canonical runtime endpoint | Existing 31-path after pin | Latest accepted pin found in fcd0f90 |
| --- | --- | --- |
| `dev/wrapper-coder/tools/host_server.py` | `dfabbe0aeac085d71a61a7251ae498070302f59ca34688c9e62786c0720c111d` | `0e13fcae57c4baa4edf1b59454546d2924c49054aebd253dd1b24f666b8e672a` |
| `src/job_search_helper/qualified_release_owner.py` | `607a08c3d3e4728e411b95cfa9e4bd54a8dbcb767560ff077351e7bc268ebec9` | `5cf4e70829ad40d797dde4779cb6a1f0a75953f303ed330c0610ee7f0e5b23e6` |
| `dev/wrapper-coder/tools/amphenol_retry_completion.py` | `54a91eb52177b21224ebf9fc2855dd026db27fd064d5f0493a07dd0967d52662` | `c7ca5f021989a5f552482be2f3eb3d40a3da428c733f49b6f8a601c05945f6ef` |
| `dev/wrapper-coder/tools/amphenol_candidate_release.py` | Not listed | `7cf2c0795925f077b5cda4a67ce6418adf6fbafae2a955732f60765951ab087f` |
| `dev/wrapper-coder/tools/amphenol_installed_verification.py` | Not listed | `aeea069ce3ea41d721f19eba73b21ac351ac820d991e3da9f85e546c33d58b8d` |

All five exact accepted blobs exist in the local backup commit. The host/owner come from `tools/sprint6-native-release-hold/`; the three Amphenol helpers come from `tools/sprint5-owned-host-release/`. The accepted host QA predates the latest typed-hold change, and the separate typed-hold QA explicitly checks that later narrow change. Thus the evidence is available, but dispersed across independently recorded slices rather than represented by one current deployment inventory.

## Concrete pass condition and next action

The coordinator can now assemble one disposable release-preparation payload from the existing enrolled baseline plus the exact accepted overlays, without altering source files in any original candidate. Reuse the existing source-scope comparison tooling and measurement functions. Record one canonical endpoint list and aggregate source/config/dependency identity, with the accepted QA source of every changed pin. Prove all runtime imports in the selected host release chain resolve within that exact packaged payload under the intended import layout; do not obtain missing modules from another temporary candidate or the live checkout. Confirm the existing exclusion list, unchanged bootstrap, and no unlisted runtime changes. The table above establishes at least two additional runtime paths and three revised after pins; it is not a claim that 33 is the final complete count.

Keep optional observe-only/status slices out unless the coordinator explicitly includes them and their accepted pins/dependencies. A package must not silently mix whichever files happen to be latest in temporary directories. Current native before-image freshness remains a separate later maintenance check and is not asserted by this offline gate.

**Why this changes the next action:** passing produces one concrete, reviewable package that can be measured, backed up and used for a future maintenance manifest; failing yields the exact missing dependency or incompatible accepted slice before any native work. It resolves a deployment preparation dependency independently of the owner choosing retained recovery versus a future disjoint case. It does not manufacture an eligible origin, clear the unfinished-cycle installation fence, or count as any live F1–F8 closure.

No additional broad regression run is proposed. The accepted real disposable host-install-retry canary, held incomplete replay, typed unfinished hold, and failed-verification rollback already cover their behavioral contracts. Run a new narrow composition only if the frozen payload comparison reveals an untested interaction or a different source pin. Otherwise the next gate remains the external native scope/eligibility decision.

## Evidence references

All reports below are under `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/`:

- `S5_S6_DEPLOYMENT_SCOPE_AND_ACCEPTANCE_20261121.md`
- `S5_NATIVE_SOURCE_SCOPE_20261121.json` and `S5_NATIVE_SOURCE_SCOPE_INDEPENDENT_20261121.md`
- `S5_OWNED_HOST_RELEASE_INDEPENDENT_QA_20261121.md`
- `S6_NATIVE_RELEASE_HOLD_REASON_INDEPENDENT_20261121.md`
- `S5_NATIVE_DIRECTION_AND_HOLD_BACKUP_VERIFIED_20261121.json`

Original acceptance contract: `/home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118/QA_FINDINGS_LEDGER.md`, F3, with F2/F6 affected by missing or mismatched retry/receipt helper bytes.

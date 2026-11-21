# Exact 44-path retirement maintenance policy handoff

Status: PASS, staged package-source author validation only. This lane initially independently reviewed the provisional package parser, then root assigned implementation ownership of this new maintenance_policy directory. The new maintained tools therefore require a separate independent reviewer before deployment.

## Source scope

Copied the previously reviewed current_site_pin controller, schema-carrying installer, gate, and focused predecessor fixtures from `/tmp/jsh-m1-scope-backup/tools/sprint6-native-site-preparation/current_site_pin/`. The gate and original predecessor test bytes are unchanged.

Installer adds only `sprint-6-consolidated-retirement-source-manifest-v1` and its exact 44-path set: prior exact 38 plus control_before_prefix_runner.py, exact_legacy_migration_runner.py, exact_recovery_pause_executor.py, retained_cycle_retirement.py, retained_cycle_retirement_control.py, and selected_recovery_runner.py under src/job_search_helper. Original 38 and legacy schemas keep their old sets, wrappers, owners, before/after endpoint, digest, mode, presence and canonical JSON checks. SourceManifest retains the schema field required by current controller. Neither the top-level provisional installer nor the 44 application after-images was edited by this implementation lane.

Controller differs from the latest accepted current_site_pin version only in two schema predicates, permitting the new exact retirement schema to use the existing installed-predecessor/current-pin contract. It still requires RELEASED terminal state, exact target/receipt and original source/guard identity, preserved predecessor source and installer bytes, installed continuity evidence, separately exact old historical and current successor pins, private current pin custody, exact successor approval, and distinct restored/fresh exchange proofs. ROLLED_BACK predecessors still require the original protected pin; legacy installed-predecessor denial remains unchanged. There is no reset of protected evidence or broad permission for other schemas.

## Verification

68 focused tests passed in 0.46 seconds under system Python with plugin autoload/cache disabled and an audit hook refusing socket, subprocess and os.system. They comprise 6 unchanged predecessor tests, 9 current-pin tests (the 7 prior cases plus retirement INSTALLED/ROLLED_BACK cases), and 53 exact package tests. Every one of the 44 omissions is refused. Extra paths, including unchanged receipt bridge and foreign wrapper, are refused. Host/store require existing before-images. Changed manifest cannot reuse its approved pin. Existing 38 and legacy 47 fixtures return identical endpoint/owner maps through old and new parser, and cross-schema widening is refused. All 44 staged after-images exactly match declared digest, mode and owner.

Initial independent provisional-parser evidence remains `/tmp/jsh-retirement-package-independent.pDsHASb2/RESULT.json` with 58 refusal probes. It confirmed all 38 original before endpoints unchanged; five existing after endpoints intentionally changed for retirement (engine, exact_cycle_recovery, exact_cycle_sync, runner, scan_request). Thus unchanged prior schema contracts does not mean all prior after-image contents are unchanged. That earlier proof also exercised dynamic controller scope: 32 package files plus 11 wrapper files plus one launcher, no fixed path-count assumption, and retained bridge drift refused. Final maintained controller retains those dynamic scope expressions unchanged.

## Native-readiness limits and next dependency

No installer/controller action, live database, service, provider, network, Google, or Jetson access occurred. Test host observations are disposable fixture evidence, not actual host acceptance. No process observer or sealed site checker was created or altered. Runtime regression and retirement-data acceptance are owned by root and separate QA.

The final native bundle must seal this exact installer/controller/gate and 44-path manifest SHA consistently in plan, checker policy and successor handoff. Reusing the old bundle/tool pins does not authorize these new bytes. The independently accepted current protected snapshot and exact historical installed continuity remain necessary, along with a fresh authorized observer/owner window and native hold/restore acceptance. No such acceptance is claimed here.

## Exact pins

- controller.py: `83eb3246bdf0d5818e322ed85fb6fd73c6f2cd0138b62ad23585d73ba0b7d708`
- installer.py: `e335cbc47c00e9e8b1bbc1d1984161e0a71789f4b776667073e008d8e0d32909`
- gate.py: `7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537`
- test_predecessor_guard.py: `0b0148e2c47ccffe9ec59691745b9055a779355ca59e00d8226a569f87cd1c8b`
- test_current_pin_independent.py: `49957fd8b53964774af0178278cf345e4d29179c9aa1179937ab49879371bcc3`
- test_retirement_package.py: `d3f1c15974fd804731787e427ef111088a8660d67f5945a9bffcdd0280350b27`
- SOURCE_MANIFEST.json: `af3a43ce8031f5e5552fd0735ed6a96d6ccdf0d02f740fa829b5e2ca19dfa047`

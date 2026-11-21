# Saronic surviving row — next legitimate recovery route

**Explicit scoped recovery implementation is required before production.** An exact pending-suffix design is documented and reusable, but the installed paths do not currently admit this Saronic source transition or execute its late-Company-control recovery to exact publication. Fresh row identity and agreement resolve evidence questions; they do not supply the missing execution authority.

Scope: source and saved design reads only. The unique live row 56891, its 18 matching visible fields, pending Last Checked/Salary/Review Status, nonempty local Decision, nonblank proposed salary, paired operations 194/195 and manual-choice record are coordinator-supplied facts. This lane did not read Sheets or application stores, run recovery, or modify data/code.

## Existing supported policy is useful

`sqlite_repository.py:24–25` includes Decision and Review Status in REVIEW_FIELDS. At `:755–763`, a current Job History manual_choices pin causes ordinary commit to remove those fields from both proposed values and expected guards; certain automated reviewed/manual-review changes instead fail. The actual behavior depends on the whole proposed operation, not merely its blank Decision. The coordinator's disposable exact-row/evidence replay through this real method will establish the effective delta under the current pin and policies.

The selected recovery helper already preserves current Decision and Review Status when they differ from frozen suffix values (`exact_legacy_migration.py:27`; `exact_selected_legacy_recovery.py:163–197`). It retains them as current-value guards instead of replaying the old proposed values. It does not independently run the normal repository's entire manual-choice/cell-policy calculation.

Salary / Range and Last Checked are not in REVIEW_FIELDS or PROTECTED_DRIFT_FIELDS. The user's requirement to preserve estimated salary when posting salary is blank is not an explanation to blank or automatically preserve this nonblank proposed salary. Its legitimate effective update must come from the actual retained source and normal current row policy, with exact before-value guard. A nonblank value alone is not overwrite authorization. Preserve current manual choices and Opportunity identity regardless.

Normal `_stage_posting` is not a drop-in recovery API: `engine.py:1179–1182` respects an active review lock, `:1214` proposes source compensation, and `:1293–1299` can reset review fields when source changes. Calling broad scrape/staging again would introduce current timestamps and lifecycle work instead of proving what remains of the original immutable plan.

## Why the installed recovery cannot perform this yet

- `exact_selected_legacy_recovery.py:250–253` requires the Company operation in the verified prefix. Saronic's late Company control does not qualify.
- `exact_control_before_prefix_recovery.py:145–156` requires a present explicit-owner Job History row already to match the proposed source hash. It has no accepted before-to-after source-transition branch.
- `control_before_prefix_runner.py:1–6,58–93` deliberately stops at a signed local hold; it neither commits Jobs nor creates a remote receipt and explicitly has no generic release fallback.
- `GENERIC_LEGACY_V2_RECOVERY_DESIGN_20261119.md` specifies freezing suffix prestate with manual/salary/source/review guards, preserving prefix without replay, verified local application, and exact receipt/readback. That is the right contract, not proof that every described case was deployed. The later current-baseline adapter report explicitly separates its staged prefix/suffix evidence from production and live publication acceptance.

## Smallest next step

Use the coordinator's copied-row replay to measure one exact effective 194/195 delta through normal SQLite policies while preserving the manual-choice row and original operation bytes. Then implement only the missing selected late-control/source-transition continuation: seal a distinct successor whose operations and fingerprints reflect that measured policy result, bound to the exact archived plan/inventory/cursor, current source-before, proposed source/evidence-after, current protected fields, Company controls and exact destination. Do not mutate the original plan or cursor to make the candidate fit.

A frozen successor must describe what will actually commit. Passing the stale operation through a commit that strips Decision/Review Status without adapting the sealed operation/fingerprints can produce a mismatch; exact receipt readback must never attest fields the normal policy suppressed. Recheck the manual pin, current Decision/review/source/salary and row policies under normal ownership before applying; do not use the Sheet row number as identity. Preserve the proven prefix and apply only genuinely pending suffix effects through the existing bounded exact-local machinery, followed by the existing exact publisher and readback. No broad sync or release-guard change follows from this work.

Minimum independent evidence is the real-policy positive delta plus refusal on changed source/manual pin/current Decision or foreign evidence, and a restart proving no prefix replay or duplicate remote write. The 18-field remote agreement is useful scope evidence but does not verify the hidden local Decision or permit ignoring it. All original plan, source versions, manual choice, history and unfinished-cycle evidence remain retained until their exact supported transitions complete.

Source roots: `/home/chris/job-search-helper_old/src/job_search_helper/`; saved design root `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/`.

# Initial measured recovery entry: narrow HOLD

Read-only source review; no data, native operation or test execution. Exact initial files in `/tmp/jsh-amphenol-exact-publication-repro.oFka58ph`:

- approved_recovery_entry.py: f2b38a1c186be1eccc9acfafce617ce655731b77dab9a30f193261485be4de7c
- recover_saved_retry.py: 26f79f91b0fb509d1cac721d84a64f5b57f376fff0e4fcdf59412c1d6cbdd1a8
- rejected_retry_plan.py: 45e3f1741246c5d549b2ffd1809b519e9570019c08d601d7618ac9580a73f677

**HOLD this initial entry pin for one small executable-identity fix.** At main's initial checks it requires isolated mode, disabled bytecode and /dev/null bytecode prefix, but does not require the installed interpreter environment. The reused bootstrap's dependency measurement reads PROJECT/.venv; it does not prove the running interpreter imports from that environment. A different isolated system/venv Python can reach the measured admission while claiming that on-disk dependency vector. Add the same check already present in the reviewed release entry: `Path(sys.prefix).resolve() == PROJECT / '.venv'`, before any bootstrap/runtime/application access. The independently pinned invocation must use the installed executable. This does not require production source changes.

The rest of the reviewed composition addresses the stated design: acquisition and validation of scraper lock occurs before importing runner; os.dup preserves the actual open-file-description lock when the first handle closes; existing `_scraper_admission(require_inherited=True)` revalidates ownership/runtime and releases the retained handle before separate closeout. Private tool modules are compiled from exact measured bytes. Canonical application imports are unchanged, and no corrected planner is imported. Exact original qualification owner/intent and destination are revalidated.

The recovery helper acquires the writer lease, rechecks current State/Company/qualified release, invokes installed full `_validate_existing_exact_plan_v2`, then constructs only the exact workbook repository and calls `_company_guard` plus `_validate_controls` before archive selection or first Jobs apply. This closes the prior projection and remote-order requirements. It invokes `_recover_exact_cycle_locked(require_frozen_plans=True)`, with no fetch, resume_local, installer or broad startup. Normal closeout runs only after the inherited scraper admission is released. Saved confirmed replay bypasses the remote factory and checks the same successor application's normal receipt/ack.

The archive/switch component has no additional concrete integrity finding in this review. Independent subprocess/disposable composition proof still needs to exercise the actual new entry, including foreign interpreter refusal and missing/foreign lease, wrong owner, remote controls drift, rollback/replay and final receipt/cleanup. The parent-reported component tests are separate evidence, not independently rerun here. `verify-inputs` is file/runtime inspection, not full native/owner/recovery acceptance.

The standalone source does not establish outer native maintenance, alternate-route/bridge fences or current observer. Those remain root's separately measured caller responsibility before any live invocation; this review does not waive them or authorize execution. No display/tool transport failure occurred.

# Staged repair QA

Result: PASS for reviewed repair behavior.

Independently reviewed coordinator retry-command integration, corrective instruction lifecycle, evidence requirements and packet selection against installed source. No blocking findings. Reviewer authored the status CLI and store refresh, so those changes require coordinating-lane cross-review rather than self-certification.

## Verification

22 focused tests passed in 1.100 seconds, including three new actual retry-command tests. A legacy assignment is created without investigation targets using the original requirement shape. Retry reconstructs the listing from the pinned source, preserves the predecessor, ignores free-text caller targets, and rebinds the successor. Changed baseline and unbound listing fail without a successor. Other tests verify stale CAS, scopes, bounded complete status, real no-progress corrective steering, packet preservation and observed redirect rendering.

The earlier test-fixture setup incorrectly attempted to mutate bound assignment fields; the production guard rejected it. The fixture was corrected to create legacy requirements at import, and all final tests passed. No runtime guard was relaxed.

## Scope and limitations

This verifies preparation and control behavior, not live wrapper correctness. The pilot still must produce an AI-authored repair and pass actual scraper inventory/detail checks. No runtime service, database, inference slot or campaign controls were changed by this reviewer. Full suite results are recorded separately. Manifest binding will be appended after release freeze.

## Reviewed file hashes

- `coordinator.py`: `9347a7f742832ae9ca01e48ee34eaa0e85a2ff2392257a5fa08f67fce3db1aa8`
- `coordinator_evidence.py`: `56279ed2c5cbc53157155fa9ccd622a2044db9aaa823cd9136a2d4349fc95d58`
- `coordinator_workflow.py`: `d02c276ccb758fd67001bc283e3f1d418b2894b04fdd3ab4a61546ac0ff85544`
- `coordinator_store.py`: `6011d5c5f45937dc3c003c4e50f305eb92eb95de6e9ef93833836e12744a6759`
- `wrapper_task.py`: `481157495e911d8c5dff18d1f94baa5c0ad6aee39ab468744302d86750431828`
- `test_retry_command_refresh.py`: `248a5c23563be8945abe82ab7a3fef809ad7021c88871ec40a55acd506295beb`
- `test_retry_investigation_refresh.py`: `13f9a2331c7c2de2237d51c4a68463511196425570a9f7eeff9950b2a5d8312e`
- `test_status_response_cli.py`: `0c1c4ae87c6f05daa8fe33fa06bb2e5aaec26077cfabb35bf61082d08e42a03a`
- `test_progress_correction.py`: `4355131b3c974c156cbbb2ef870d10cc09b2855073a0e766dff9781b45c7028a`
- `test_pilot_evidence_packet.py`: `fe66c5e488780249817453459631cb1743c131e7e47b305b58da918450a5459c`

## Final manifest binding

Result: PASS. Canonical manifest digest `a57b934866cb677e309af6f6bcfe16500f76547782e8df2941d4f28950defa5c`. Independently verified all 69 staged source entries and 682 installed prerequisite entries match the manifest, all 10 reviewed file hashes remain unchanged, and migration inputs are empty. Reviewed the separate scoped rollout report; its retained safety gates and no-migration behavior agree with this release.

The coordinating lane cross-reviewed this reviewer-authored CLI/parser and retry store/CAS changes. Root reported full suite terminal exit 0; independently inspected saved `final-tests.log`: **309/309 passed in 26.699 seconds**. Counts overlap the 22 focused tests and must not be added.

This PASS authorizes the reviewed staged candidate for the paused deployment procedure; it does not certify installed behavior or the live GDLS wrapper.

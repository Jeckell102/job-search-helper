# Sprint 4 joint release repair fixture handoff

**All 10 tests passed** against the exact repaired staged tools. Two focused negative controls against the pre-repair tools reproduced the original acceptance of a different physical endpoint mount and an absolute directory opened through an ancestor symlink.

Harness and stubs live at `/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1`. It consumes four copied tools from the specified source directory. The 47-endpoint fixture pins the nominated dispatcher-binding QA after-images and the earlier disposable, rolled-back before-images. The final harness reads no current production source or state.

```bash
cd /tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1
/usr/bin/python3.11 -I -B test_combined_release.py \
  --controller-source /tmp/jsh-s4-combined-release-tools-repair.JpgiG3IM
```

## Restoration tests

- The fixture verifies that the initial `restoring` callback sees the runtime marker and both fake units still held. It verifies that `restored` sees the original unit states restored, the marker and service sentinel absent, scoped source and wrapper module origins correct, and the controller journal still `RELEASING`.
- The stub kills the controller during the independent `restored` callback after service restoration and before `RELEASED`. Same-direction replay receives a fresh `restoring` callback with the marker already absent and wrapper active, then a fresh `restored` callback. The transaction finishes with exactly one fake wrapper start across interruption and replay. Attempting to reverse direction while `RELEASING` is refused.
- An explicit `restored` refusal returns a held result. The test verifies the original marker payload, recreated service sentinel and both unit conditions, stopped units and routes held before allowing same-direction retry. The subsequent wrapper restart is expected because the refusal stopped it.
- The earlier partial wrapper, guarded package publication, transaction replay and candidate-independent rollback exercises are retained. The added anchor tests replay with an aliased `dev` ancestor and open a byte-identical directory through an absolute ancestor symlink. Both refuse. A child-process fixture forces a different mount ID for the actual open wrapper file descriptor and proves the installed loader rejects it with unchanged bytes. This test injects the mount ID in process and uses no mount operation.

The fixture service manager, direct-launch fence and restored host attester are synthetic. Their callback and receipt evidence does not establish that the real host closes its direct routes or that wrapper restart is free of side effects. The coordinator owns the real host check and release decision. No live action or shared source edit was made.

[Fixture runner](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/test_combined_release.py) · [Stub logic](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/fixture_stubs.py)

[Final suite](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/repaired-suite-final.log) · [Frozen tool pins](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/run.eowdlvfl/frozen-tool-input.json) · [Pre-repair negative controls](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/pre-repair-negative-controls.log) · [Restoration Interruption attestations](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/run.eowdlvfl/test_interrupted_after_restoration_replays_without_duplicate_service_start.uttdc3bg/attestations.jsonl) · [Restored Refusal attestations](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/run.eowdlvfl/test_restored_attestation_refusal_reinstates_marker_and_unit_holds.ui8zsldt/attestations.jsonl) · [Joint Install And Rollback attestations](/tmp/jsh-s4-combined-release-fixture.repair.7m6CcBS1/run.eowdlvfl/test_mixed_wrapper_fault_then_published_fault_reentry_and_payloadless_rollback.etjp5_p7/attestations.jsonl)

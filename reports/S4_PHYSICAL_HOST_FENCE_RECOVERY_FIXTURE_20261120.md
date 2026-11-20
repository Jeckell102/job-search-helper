# Sprint 4 physical-host recovery fixture

**Result: all 14 disposable regressions and all four focused recovery tests passed on the same repaired tool pins.** Both directions from the newly approved recovery states were verified with the candidate removed. No staged-tool defect reproduced in the tested scope.

This overlay under `/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg` tests the revised controller from `/tmp/jsh-s4-combined-host-fence-recovery.fOcKhtD5`. It preserves the same 47 source endpoints and independent before/after image pins. The prior physical-host evidence remains in its original directory with its own frozen tool pins.

```bash
cd /tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg
/usr/bin/python3.11 -I -B test_combined_release.py \
  --controller-source /tmp/jsh-s4-combined-host-fence-recovery.fOcKhtD5
```

## Recovery cases

- A refused restored-host attestation leaves durable `RELEASE_REFUSED` with the marker and unit holds in place and the canonical host path physically absent. If the controller dies immediately after writing that intent, the next explicit attempt reestablishes all holds before proceeding. The fixture also interrupts recovery after host fencing to verify that the journal still says `RELEASE_REFUSED`. A new explicit same-direction command reopens and finishes.
- Explicit rollback works from both a completed re-hold in `RELEASE_REFUSED` and an interrupted `HOST_REOPEN` with the new host already present. The test removes the candidate tree before rollback and verifies the full old pair, old endpoint absences, prior namespace and unrelated source preservation, and identical rollback replay. Both rollback routes attest a physically absent host before changing direction.
- A controlled error after the host atomically appears, but before `HOST_REOPEN` advances, leaves no running fake service and recreates the physical absence and runtime holds. A subsequent exact install starts the fake wrapper once.
- The inherited tests cover close intent before unlink, physical absence with the original package visible or parked, both sides of host reopening, after-restoration interruption without duplicate service start, package publication interruption, exact mount and directory checks, and payloadless rollback. The inner joint receipt must carry `wrapper_host_fenced: true`.

Both absolute and project-relative Python calls are attempted only when the exact fixture source path is absent. They fail opening the script with exit 2 and `[Errno 2]`. The tests never execute the host file itself. Fake unit and site checks cannot establish real host closure, alternate route containment, or production wrapper catch-up behavior. No staged tools, production files, services, job data, or external systems were modified.

[Prior pin handoff](/tmp/jsh-s4-physical-host-fence-fixture-handoff.md) · [Recovery fixture](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/test_combined_release.py)

[Full run](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/recovery-full.log) · [Focused run](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/recovery-focused.log) · [Frozen tool pins](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/run.c2878suv/frozen-tool-input.json) · [Post-open injected refusal](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/run.c2878suv/test_post_open_refusal_reestablishes_physical_absence_before_next_command.1ztn3s37/atomic-faults.jsonl) · [Journaled recovery attestation](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/run.c2878suv/test_persisted_release_refusal_resumes_holds_before_allowing_reopen.b12to87p/attestations.jsonl) · [Physical fence and reopen attestation](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/run.c2878suv/test_physical_host_absence_through_persisted_close_and_reopen_interruptions.arugawlt/attestations.jsonl) · [Payloadless rollback 1](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/run.c2878suv/test_payloadless_rollback_after_refusal_or_unfinished_host_reopen.buws4po2/invocations.jsonl) · [Payloadless rollback 2](/tmp/jsh-s4-combined-release-fixture.host-recovery.izeeo8lg/run.c2878suv/test_payloadless_rollback_after_refusal_or_unfinished_host_reopen.stvkhufi/invocations.jsonl)

# Sprint 4 physical-host recovery fixture

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

# Sprint 4 physical wrapper-host fence fixture

**Previous staged pin.** Twelve fixture cases were verified across the suite and focused reruns. The suite’s sole remaining failure came from the fixture trying to run its intentionally canonical-only Python probe through a deliberate ancestor alias. The corrected negative case passed on identical tool bytes. The expanded interruption case covered both canonical and parked host-fenced callbacks. This report describes the earlier pin only. The separate recovery-tool revision changes refusal and rollback transitions.

Fixture overlay only. The harness under `/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU` consumes the staged tools under `/tmp/jsh-s4-combined-host-fence.Csm9gwcg`. It preserves the repaired suite, the 47-path manifest with the same earlier fixture before-images and dispatcher-binding QA after-images, and the established Sprint 4 schemas. Each run freezes a fresh local copy of the four supplied tools. No staged or live source was edited.

```bash
cd /tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU
/usr/bin/python3.11 -I -B test_combined_release.py \
  --controller-source /tmp/jsh-s4-combined-host-fence.Csm9gwcg
```

## Verified boundaries

- `host-fenced` accepts the requested canonical or parked package only under the runtime marker and both stopped fake units, and requires the real fixture pathname `dev/wrapper-coder/tools/host_server.py` to be absent. `before-host-reopen` requires exact bytes, ownership and modes for the other 46 endpoints, the canonical package with its temporary initializer gone, and the marker and unit holds. The inner receipt must say `wrapper_host_fenced: true`.
- For both callbacks, the fixture checks physical absence before launching the actual Python interpreter on the absent script. It tests an absolute pathname and the same relative pathname from the fixture project directory. Both must fail during script opening with exit 2, `[Errno 2]`, the exact absent pathname and empty stdout. The fixture checks absence again afterward. No existing host image is executed.
- The crash sequence stops after the close intent is durable and before unlink, then stops after verified physical absence while the close is still journaled. It stops again before host recreation in durable `HOST_REOPEN` and immediately after recreation but before leaving that phase. Re-entry verifies and reuses the already present correct endpoint, witnessed by unchanged inode and change time, then starts the fake wrapper once. The earlier two-fault install, wrapper cache check and rollback without staged after-images are retained.
- An explicit restored-host refusal records `RELEASE_REFUSED` before the re-fencing attestation. The runtime marker, both unit conditions and physical host absence are verified before `HOST_REOPEN`. A separate abrupt death after the refusal is persisted tests the gap before any re-hold. The next same-direction invocation restores all holds and exits with the readiness requirement. A later invocation performs the exact reopen and safe restoration.
- The installation and rollback suite still covers swapped or aliased source directories, the endpoint mount guard, historical namespaces, unrelated sources and cache, and restoration replay without a duplicate start.

The Python missing-script proof is real but is limited to the two canonical-path spellings inside the disposable fixture. Service drainage, direct fencing outside that exact pathname, exclusive ownership of alternate host paths and real post-restore effects remain separate live-host prerequisites. There were no production or canonical application operations.

[Fixture runner](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/test_combined_release.py) · [Fixture attester and Python probes](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/fixture_stubs.py)

[Suite results](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/physical-host-final.log) · [Corrected alien-parent case](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/physical-host-ancestor.log) · [Expanded interruption test](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/physical-host-boundaries.log) · [True missing-script attestations](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/run.dthn7aol/test_physical_host_absence_through_persisted_close_and_reopen_interruptions.9_amz5__/attestations.jsonl) · [Source atomics](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/run.dthn7aol/test_physical_host_absence_through_persisted_close_and_reopen_interruptions.9_amz5__/atomic-faults.jsonl) · [Frozen tool pins](/tmp/jsh-s4-combined-release-fixture.host.ba5KE9CU/run.9m5il6fl/frozen-tool-input.json)

# Sprint 4 combined source transaction fixture handoff

**Result: all five independent fixture tests passed** against the frozen copy of the staged combined tools. The main test recorded a stopped installer with one changed wrapper file, a killed controller with all three wrapper files changed at guarded package publication, and successful install and rollback replay. The initial harness assertion omitted the receipt record's nested inode/mount fields; the corrected assertion verified each directory against its actual fixture inode. No staged-tool defect reproduced in this scope.

The independent harness is in `/tmp/jsh-s4-combined-release-fixture.YsdYntjm`. It accepts a controller source directory and freezes copies of the supplied controller, installer, gate and hold verifier. The test runner creates every plan, tool copy, host checker, service stub, lock and runtime witness inside a new mode-0700 fixture below that directory. It does not edit the supplied tools or QA snapshot.

```bash
cd /tmp/jsh-s4-combined-release-fixture.YsdYntjm
/usr/bin/python3.11 -I -B test_combined_release.py \
  --controller-source /tmp/jsh-s4-combined-release-tools.wkZs5rUo
```

## Scope and fault coverage

- The fixture manifest has 47 exact endpoints. It uses the earlier rollback preimages and the nominated `/tmp/jsh-s4-dispatch-binding-qa.i45G33KN` after-images. Comparing the two measured after-vectors confirms the dispatcher and ordinary settlement files are the only changed previous package endpoints. The three wrapper replacements match the earlier audited pins at their real `dev/wrapper-coder/tools/` relative paths, `coordinator_receipt_host_bridge.py`, `coordinator_store.py` and `host_server.py`. Their old source bytes were read and matched against the earlier before hashes. No production state or credential was read.
- The main test starts with the matching old pair. At the first attested checkpoint with exactly one changed wrapper path it kills the fixture installer. Both fake units, the runtime marker, the parked-package import gate and the stub's persistent direct-launch fence remain closed. At the published checkpoint on re-entry, the host stub verifies the complete new vector, then kills the fixture controller before admission. The canonical stock import remains blocked by the empty initializer and both wrapper routes remain held. The complete installed pair is verified on re-entry before route reopening and receives an identical receipt on replay.
- Rollback runs after deleting all staged after-image files. It checks restored old path pins, absent additions, identical rollback replay, wrapper stale-cache removal, the preserved unrelated wrapper file/cache, and a same-basename untouched file inside the package. It also checks the two prior parked namespaces, opaque State/Jobs/Inbox witnesses, existing lock identities and the fake sync expiry. The receipt is checked against the named source directories and common mount witness.
- Negative checks reject project or candidate wrapper-directory symlinks, a byte-identical replacement wrapper parent during replay, an occupied Sprint 4 namespace, and a host-attester refusal when the persistent direct fence cannot be established. The legacy Sprint 3 tools reject these real wrapper manifest paths before writes, with the synthetic old pair still available.

## Evidence and boundaries

The package import probe executes only a fixture-owned trivial initializer. Wrapper origins are resolved without importing the supplied host or starting a listener, and real source is parsed without execution. Direct and supervised wrapper admission are observed through the fixture fence and fake service manager. The supervisor stub also refuses any activation against a mixed endpoint vector. This tests controller interaction with a persistent host boundary. Actual MuleLab direct routes, alternate checkout writers, service-manager state and host checker remain independently owned release prerequisites. There is no live execution path in the supplied fixture plans.

[Harness](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/test_combined_release.py) · [Host and service stubs](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/fixture_stubs.py) · [Legacy negative control](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/legacy-negative.log)

[Passing test run](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/combined-tests-final.log) · [Frozen tool pins](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/run.npy7t4ue/frozen-tool-input.json) · [Fault and checkpoint attestations](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/run.npy7t4ue/test_mixed_wrapper_fault_then_published_fault_reentry_and_payloadless_rollback.gp54lr2_/attestations.jsonl) · [Command outcomes and transaction receipts](/tmp/jsh-s4-combined-release-fixture.YsdYntjm/run.npy7t4ue/test_mixed_wrapper_fault_then_published_fault_reentry_and_payloadless_rollback.gp54lr2_/invocations.jsonl)

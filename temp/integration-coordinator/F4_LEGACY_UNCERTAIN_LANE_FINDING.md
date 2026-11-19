# F4 follow-up: legacy request bypasses an uncertain lane

Observed 2026-11-19 during read-only coordinator verification of the current
uncommitted F4 corrections. This finding is separate from the five previously
reviewed corrections. No production call or file was changed.

## Reproduction

Using the staged `test_wrapper_inference.InferenceTests` mock environment and
a new temporary receipt database:

1. Reserve a controlled request using its valid fingerprint and owner.
2. Mark that receipt `UNCERTAIN`.
3. Call staged `wrapper_inference.infer(engine, legacy_three_field_data, store)`.

Observed output:

```
{'retained_status': 'UNCERTAIN', 'legacy_native_calls': 1}
```

The legacy branch never calls `control_store.begin`, so the retained uncertain
request does not block its native model invocation. The same problem exists
after service restart when a running receipt becomes uncertain. The inspected
reference `tool_runtime.native_turn` uses a process-local engine gate, which
cannot establish whether an earlier disconnected backend request is finished.
This probe proves wrapper dispatch bypass, not actual simultaneous backend
execution; no live backend was used.

## Required disposition before F4 closure

Reconcile backward compatibility with the explicit shared-lane hold rule.
Prove that a legacy wrapper request cannot submit work while a controlled
request is uncertain. A simple read-before-start check alone needs race
analysis; inspect atomic admission and all supported paths through this lane.
Also examine whether ordinary service callers sharing the engine can bypass
the same unknown-execution hold, and document the intended lane scope.

Leave the earlier five-correction source acceptance scoped to those five
requirements. This additional finding remains open until repaired and tested.

## Independent recheck after the owner's correction

The owner changed the staged wrapper to reject the three-field payload whenever
a control store is supplied. Repeating the original isolated probe returned:

```
{'legacy_rejected': True, 'retained_status': 'UNCERTAIN', 'legacy_native_calls': 0}
```

This closes the demonstrated wrapper-route bypass at source level. Compatibility
changes: the upgraded HTTP wrapper endpoint requires controlled requests even
when idle; direct legacy callers without a control store still work. Coordinate
host/endpoint rollout accordingly. The broader device-level hold and backend
inactivity proof remain deployment gates and were not verified by this probe.

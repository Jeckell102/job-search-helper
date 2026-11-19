# Exact recovery lock-owned context — independent QA failure

Date: 2026-11-19

Affected candidate hashes:

- source: `1b433efdd76c1958fe3a5f5d95c73bb5ab5c5be8fbd8acd1b134b030b16d650e`
- tests: `18be5328eae7b495b1a9ae5445edf4172a6f9f0b21743a99c66e37fa95e83283`

## Result

REJECT. No runner or live activation is authorized.

The candidate issued an active registry-bound capability through a ContextVar.
Two adversarial cases still reached `State.cycle` instead of being rejected
before protected access:

1. the same live capability could be reused repeatedly in its issuing context;
2. a context copied after issuance inherited the same ContextVar capability and
   could use it while active.

The existing cross-context test copied the context before issuance and did not
cover this case. The independent probe reached State three times across the
original invocation, a repeated invocation, and the copied-active-context
invocation.

Canonical regular-file validation, normal-lock derivation/contention,
wrong-thread, copied-object, expired, wrong-path, dependency construction,
selection, and isolation behavior otherwise passed. The focused and adjacent
sets passed 80 tests in 3.90 seconds, but green tests do not waive the escaping
capability defect.

## Repair direction

Do not expose a reusable held-lock capability. Replace the new boundary with a
public lazy-factory entrypoint that validates the exact request, acquires the
real normal scraper lock itself, invokes one dependency context factory only
inside that lock, verifies the constructed Engine uses the exact canonical
State path, executes the existing locked core, and closes dependencies before
releasing the lock. The dependency factory is construction, not lock proof;
the function itself owns the real lock.


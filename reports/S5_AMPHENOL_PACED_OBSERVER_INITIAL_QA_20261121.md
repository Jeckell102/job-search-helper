# Initial observation-only evaluator QA

**REJECT** the evaluator at SHA-256 `452bbbc5df970765e06bb1225102ee34f0d593d46de5f4159730ab7eab4db287`. Its maintained fake suite passed three tests. Two independent probes using the actual immutable candidate dispatcher and adapter, a synthetic browser and an injected fixture clock reproduced the missing guards.

- Actual first detail HTTP 429 with Retry-After 3600 stopped the normal adapter at one detail call. The evaluator dropped the exception-path call evidence and produced a generic failure instead of a terminal rate hold with the observed schedule.
- On the synthetic unpaced control, actual observed starts were 0s and 3s, with final inventory start at 6s. The evaluator nevertheless emitted its success state. The normal adapter's pacing used in later positive proofs is unchanged.

Original evaluator, test sources and logs are preserved in this directory. No external contact, service action, live state opening, or writes to the reviewed source occurred.

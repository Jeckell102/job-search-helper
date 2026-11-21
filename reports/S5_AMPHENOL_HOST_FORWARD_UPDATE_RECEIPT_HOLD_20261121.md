# Final-pin recheck of Amphenol host-only updater

**REJECT** updater `976c38d59c0a06a10061bada52481829a222b2ba9d084b011e3ba9bd8d81e659` on a reproduced durable receipt mismatch. The earlier rollback failures are repaired.

| Evidence | SHA-256 |
| --- | --- |
| Maintained tests | `0732088142df9f918ad5ae9d580551049ee530d01d44b934c8628cfb407d5c9c` |
| Native launcher | `fc6441c188156d3407ef23b3fd4ad1215d55483a31017d3ece12ccfe437da07c` |
| Passing maintained and previous independent replay result | `d51b63b3efb8b29586485a167035b743409c3c5fb873004a02d49437800171d5` |
| New receipt boundary probe | `60a811611ca2db89d7bc6867991ade36ba35295ae3e1a9a38b6be3180462ec0b` |
| Failed receipt boundary result | `05c1b682399d5d69d1f352b2801099d4db426b707f4ca018f50b6558358cf767` |

All 11 maintained and prior independent checks passed. The stage covers refusal before initial stop, failure after candidate readiness, replacement that changes bytes before raising, start that loads the candidate before raising, and failed readiness of the restored wrapper. The launcher supplies `stopped_probe`; it checks inactive, MainPID 0, and absence of the enrolled listener. Parent separately reports observed native preflight success.

The additional test writes and links the success receipt using the real disposable filesystem. It injects one error only on the subsequent receipt directory fsync. The final file and loaded wrapper agree on the original bytes, while the canonical receipt reports `HOST_FORWARD_INSTALLED`. The failure path restores the original and suppresses rollback publication because the success receipt name exists. Receipt publication and runtime compensation need a shared commit boundary. On ambiguous durability, preserve the verified candidate and hold, or prove durable removal of the success name before compensation.

The first rejection remains preserved at `/tmp/jsh-amphenol-host-forward-independent.Ij1ijZdX/INITIAL_QA.md` with SHA `6de1f7b91aa3114f14ea4485ae75e578599693ff835cb6c450f28eb59504c057`. The second remains preserved at `/tmp/jsh-amphenol-host-forward-recheck.LRF70qcz/INDEPENDENT_QA.md` with SHA `ea8f6541ad26d8a36aaf0f439bf4d0cba58e15e348688869f20c0046aad0e2ca`.

This lane used static source, disposable source files and a local service simulation. No native execution, process control, application data, or network calls.

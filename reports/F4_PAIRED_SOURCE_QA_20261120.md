# Sprint 2 F4 paired source QA

**ACCEPT the reviewed paired source for controlled deployment review. HOLD full deployed F4 acceptance.** Both findings from the earlier independent review are corrected in the candidate pair. The paired tests used a synthetic token, disposable SQLite databases, an ephemeral loopback HTTP server and a fake native inference callback. This review performed no production operation.

## Findings and recovery behavior

| Check | Result |
| --- | --- |
| Earlier MuleLab reply-binding failure | Missing control metadata and a foreign request ID were rejected. The wire matrix also rejected a nonterminal synchronous reply and wrong digest, inconsistent usage and oversized counters. The exact terminal envelope passed. A request with no local binding never reached HTTP. A control-only reply could trigger one owned status lookup, with zero tool execution and no replay. |
| Earlier Jetson duplicate metadata exposure | Running and completed duplicate replies used the same public fields as owned status. They excluded the fingerprint, owner generation, internal backend generations, and model message. The same controlled request invoked the native callback once. |
| Synchronous paired contract | The current MuleLab client accepted a real fixture response from the candidate Jetson handler. The retained Jetson digest matched MuleLab's accepted response after removal of the transport envelope, and usage matched. The local path charged one call and the observed 20 tokens. |
| Exact recovery command | A separate paired fixture sent `status`, repeated `observe`, a refused `settle` while backend inactivity was false, and one successful `settle` with positive simulated evidence. The remote stale owner was refused for both status and settlement. The first terminal settlement recorded `FAILED`. Repeating all three operations produced zero network calls or accounting changes. The recovery sequence submitted zero inference POSTs. |
| Transport loss after remote completion | The supplied accounting proof ran with the explicit candidate directories. It recorded one inference POST, one native call, stale-owner HTTP 400, Jetson `COMPLETED`, MuleLab `RESPONSE_DROPPED`, task `PAUSED_RECOVERY`, one charged call, 20 settled tokens, and zero new tool receipts. Its four status requests include two stale-owner probes, the successful restart lookup, and one explicit terminal replay. Subsequent startup skipped the terminal receipt. |

**Test results:** 57 focused MuleLab tests and 28 Jetson tests passed. The earlier MuleLab runs caught three obsolete fixtures during the contract change, including HTTP error tests missing the newly required binding and a retained receipt fixture missing the new public shape. A clean rerun passed after those fixtures were updated. The accounting proof used the actual candidate HTTP client, handler and both durable stores. The fixture reopens the coordinator store and covers the fault boundary by discarding the committed response.

## Exact source identities exercised by the accounting proof

| Source | SHA-256 |
| --- | --- |
| MuleLab `coordinator.py` | `b9fe2de378bcf942e1a7123e3d3e727ec97c41c803703ef6a2bae982a6a74175` |
| MuleLab `coordinator_inference.py` | `33b453fce23359b61f32f29d7dc1c3d40b8231e8a1c06d1b08862351da9a8bba` |
| MuleLab `coordinator_store.py` | `558f0e4385148a045458c456df8b3ced57631cb00dc06bf2076798459c8ffa2f` |
| Jetson `server.py` | `054c714a52ad3c83fdcc2087151d3557cef8ac408718071221e24f0e313b6469` |
| Jetson `wrapper_inference.py` | `d338a50d2dee7c00b4d8a677da9ad02c3897c30008dc246382e6be336fe8a218` |
| Jetson `inference_control_store.py` | `e8dccc2c5b7532b959592cb8ba08fcb8cfe1275bdf432ff15895b30450998a80` |

## Remaining gates

1. Pin the tested source, preserve the read-only deployed transport attestation supplied by the coordinator, and prepare scoped recovery copies and verified rollback for both hosts. Keep broad controls and the single inference lane in their recorded safe state. Legacy ambiguous receipts without a valid binding remain held.
2. Only after authorized deployment, verify the installed file identities, protected controls, receipt aggregates, and effective authenticated routing with independent read-only QA. The fixture proves the candidate behavior. The deployed transport attestation belongs to the existing release.
3. Carry forward the accepted real Jetson backend-interruption proof for the unchanged inactivity/recovery mechanism. The paired accounting proof used object/store reopening. If final acceptance calls for an actual coordinator process exit, exercise that one boundary with the same credential-free HTTP fixture and verify the same terminal receipt and counters after restart. If a fresh deployed cross-host observation is required, authorize one synthetic dropped-response run through the installed coordinator separately. Another Ollama interruption would duplicate accepted evidence.

[Earlier independent gap review](/tmp/jsh-s2-independent-gap.md) · [Accounting proof](/tmp/jsh-s2-accounting-proof.py)

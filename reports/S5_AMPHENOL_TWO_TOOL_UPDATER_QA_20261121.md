# Independent two-tool rollback recheck

**ACCEPT for the corrected rollback on updater `cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597`.** Four disposable tests passed in 0.11 seconds. The original independent test ran unchanged. After a loaded-hash mismatch and a rollback stop that stopped the wrapper before reporting an error, the exact stopped probe permitted restoration in host-then-Store order. The fixture verified both old files, original loaded hashes after restart and a terminal rollback receipt carrying both predecessor pins. The operation still reported its original loaded-hash failure. Source comparison confirms that an unproven stop still holds before any rollback source write.

Original QA report and failure were rehashed unchanged. This recheck used fixture callbacks and private files only.

| Artifact | SHA-256 |
| --- | --- |
| Unchanged independent test | `23ea7c001f16a8a8d8e35674dffe99b9685e84dac2b0a97eda6c70ed58494cd2` |
| Original rejection report | `1a58135c2364533172004831b96073aae4b413d0c90343896a483f2ecb31402b` |
| Original failure result | `4523ddabb0103b42faa2d27b17fb23bfff5da256550af38c0f475f943059ca84` |

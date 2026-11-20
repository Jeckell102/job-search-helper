# Sprint 2 F4 independent deployed QA

**Installed source and operational checks: ACCEPT. Full deployed F4 acceptance: HOLD pending the separate bounded accounting proof.** This reviewer performed read-only host and receipt checks and did not issue any inference.

## Installed identity and rollback

All six source hashes match the independent paired-source accounting proof. The two additional MuleLab files used by the live-proof preflight match the reviewed source tree.

| Host and file | Mode | SHA-256 |
| --- | --- | --- |
| MuleLab `coordinator.py` | 0664 | `b9fe2de378bcf942e1a7123e3d3e727ec97c41c803703ef6a2bae982a6a74175` |
| MuleLab `coordinator_inference.py` | 0664 | `33b453fce23359b61f32f29d7dc1c3d40b8231e8a1c06d1b08862351da9a8bba` |
| MuleLab `coordinator_store.py` | 0664 | `558f0e4385148a045458c456df8b3ced57631cb00dc06bf2076798459c8ffa2f` |
| MuleLab `coding_tools.py` | 0664 | `4eb25d5c73f4040216fbdb44fab5142fdc2888e6fc738c01f5845192ea3d1644` |
| MuleLab `host_server.py` | 0600 | `ebb7f0904991642ac54615d3c0aacba6f9499ade4f16e4e48966829a857e8ce7` |
| Jetson `server.py` | 0600 | `054c714a52ad3c83fdcc2087151d3557cef8ac408718071221e24f0e313b6469` |
| Jetson `wrapper_inference.py` | 0600 | `d338a50d2dee7c00b4d8a677da9ad02c3897c30008dc246382e6be336fe8a218` |
| Jetson `inference_control_store.py` | 0600 | `e8dccc2c5b7532b959592cb8ba08fcb8cfe1275bdf432ff15895b30450998a80` |

- The MuleLab two-file rollback matched the independently retained pre-deployment hash and mode for each file. The Jetson two-file rollback hashes matched the prior reviewed adapter source and both copies were mode 0600. The host-side installed manifests passed. Both hold-release records were present and the maintenance sentinels were absent. Jetson retains its rollback procedure and prior change-control documents.
- The wrapper host and tunnel were active and enabled, and Jetson's orchestrator and Ollama were active. The local listener belonged to the tunnel's systemd main process. The tunnel routed `GET /healthz` to the Jetson service and returned 200, version 0.2.2. Ollama's PID and monotonic start identity matched the recorded pre-deployment generation.
- The wrapper PID was sole owner of both scheduler and supervision locks. The scraper, writer, review-writeback and integration-install locks were unheld at inspection. Sync remained inactive and disabled with its existing expiry drop-in.
- MuleLab held queue, campaign and autopilot off and the pilot unset, with no active tasks or unresolved inference. Its control generation was 463 and its existing inference aggregate was 20 `COMPLETED` and one `RESPONSE_DROPPED`. No company-intake policy journal was present and the held company-only request remained intact.
- Jetson receipt integrity was `ok`. Its pre-proof aggregate was one `CANCELLED`, one `COMPLETED` and one `FAILED`, with no `RUNNING` or `UNCERTAIN` rows.

## Gate still open

Obtain the separate operator-run synthetic evidence for the exact installed pair. It must record one real inference submission, a response lost after remote commitment, owner-bound terminal status, one local charge and usage adjustment, no replay or tool execution, and restored terminal-only receipt aggregates and continued holds. The earlier accepted Ollama interruption remains evidence for the unchanged safe-terminal recovery path.

[Paired-source QA and fixture proof](/tmp/jsh-s2-paired-source-qa.md)

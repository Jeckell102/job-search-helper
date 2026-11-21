# Independent source QA — original Amphenol host-only updater

**REJECT** the original updater. A failed candidate readiness check can leave the candidate running while the receipt attests rollback. A refused initial stop also replaces the original inode without ever installing the candidate.

| Evidence | SHA-256 |
| --- | --- |
| Captured original updater | `049d44fac4a0f161c185184da970ebdba66deb5914a563f9832403bfbf34f6d9` |
| Captured maintained tests | `74708394a4ba72b696926a82ed55360c1574fc253b2a2532eaae9b287381551b` |
| Independently reproduced -03 before-image | `137563add244929e36f53dc0e4b87f2f9a9faaeb22a799102c89e9b939b79eae` |
| Previously reviewed frozen candidate pin | `5abe835b6b550f3bb81a7c787e97382910ce1d882687521c60e3e8ec630a37ad` |
| Independent tests | `5d02ff9393b3304cc56194418664b09553c70ddfb6917297fb79482d9cf8c06d` |
| Initial test output | `d0c4182d6d7d48ab5aa7904267332b7d64bee581caa380afff752ab7f2732da7` |

Three maintained tests passed. Two independent tests failed using real disposable source files and a service callback that only loads files when starting an inactive unit.

- After the first start loads the candidate, readiness fails. Calls are `stop, start, start`. The final source file is the original, the active process still carries the candidate, and the durable receipt reports `HOST_FORWARD_ROLLED_BACK`. The maintained rollback test records both start calls but never models an already active service.
- If the first stop refuses before any source action, the cleanup still unconditionally replaces the before-image and the physical inode changes. No candidate bytes were installed.

The repair must stop the candidate before restoring the source whenever it may have started, then restart and verify the original wrapper before reporting rollback. A failure of the first stop must hold without replacing the source or claiming verified rollback. An inability to establish which runtime is active must also hold.

The original code scopes direct source writes to `host_server.py`, checks the other eight hashes and retains both the existing deployment lock and controller terminal context around that scope. Exact native predecessor authority and the supplied service/idle/exchange callbacks are a separate integration boundary. This run used only disposable temp files and blocked network, subprocesses and protected file opens.

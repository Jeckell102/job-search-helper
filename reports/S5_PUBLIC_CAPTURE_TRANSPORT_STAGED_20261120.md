# Sprint 5 direct public capture transport

Staged for independent review. The adapter implements the accepted capture helper's `open_get` interface with one direct HTTP/1.1 GET, independently selected public numeric endpoints, a verified TLS hostname and bounded explicit body framing. The adapter adds no runtime library, HTTP client process, resolver, or application entry point.

## Pins

| Staged file | SHA-256 |
| --- | --- |
| `dev/pre_release_validation/rippling_public_transport.py` | `1df2a46f9f0aff246a9e0b1c5a74a96bf3d012a5a861ff9253dc7646809c708a` |
| `tests/test_s5_rippling_public_transport.py` | `dfff7790ef0221f3fed687d86166b6442a6edf306a59c0e3d82a73418479b7e6` |
| Accepted capture helper dependency | `6a8ff763c69f7aeebf3da0f60b85a2d7deba17c9f2b20677d9a5e75db58bd571` |

## Contract

- Construct `PublicCaptureTransport` with the measured owner's exact, independently authorized map of one canonical numeric public address per origin. This step creates the verified TLS context. The adapter makes no DNS lookup and never redials or consults ambient proxy configuration. The TLS connection uses SNI and required certificate and hostname verification for the exact URI host, whichever approved IP is selected. TLS uses the same compiled trust path policy as ordinary direct capture, requires TLS 1.2 or later, and precludes key logging. The existing ordinary transport does not supply this interface because it retries, normalizes the headers, and does not give the required absolute I/O deadline.
- The allowlist includes only the two exact employer pages, the one non-followed PDW alias, the two canonical board roots, bounded canonical page numbers, and canonical UUID-shaped detail URLs. The accepted collector still proves listing membership and sequence. The adapter rejects unreviewed statuses and responses that introduce an unexpected Location or Refresh. One socket and one serialized GET are used per call.
- HTTP/1.1 status and header blocks are retained as original ordered bytes. Only Forterra careers may precede its final response with one 103 block. The request asks for identity encoding, and missing or identity Content-Encoding is accepted. A successful body has one explicit Content-Length or complete chunked framing. Duplicate or conflicting lengths, close-delimited bodies, chunk extensions or trailers, and premature EOF hold. Chunk framing has a separate 256 KiB input cap. The returned entity contains only the original body bytes, with transport framing removed. The adapter closes after the exact framed response and never reads another response from that connection.
- Nonblocking connect, TLS handshake, send, headers and body use the slot-compatible Linux CLOCK_BOOTTIME deadline. Both separate header/entity caps and the combined cap apply during reads. A normal context exit requires fully consumed framing and an elapsed check after descriptor cleanup. The collector records the attempt and completion as before.

## Verification and remaining gates

**89 passed in 3.43 seconds** with isolated system Python 3.11. This includes 47 new synthetic socket/TLS cases, 27 maintained capture cases, ten original independent capture cases, and five independent callback cases. The real capture helper completed its 31-exchange synthetic ledger through this adapter. Tests cover raw duplicate headers and entity preservation, TLS constructor policy and hostname binding, no follow-up request or retry, malformed and quiet truncated framing, separate and combined byte caps, and expiry in every I/O phase. The test harness forced all direct connection and DNS operations through synthetic fixtures.

The measured owner has yet to supply and pin current endpoint selections and the loaded transport capability. No live service support has been shown for the deliberately narrow HTTP/1.1 and identity-framing policy. Live rollout would need separately approved transport and egress verification before using the adapter. Ledger implementation, capsule custody, and later approval freshness remain separate caller dependencies. No application code, candidate, accepted capture helper, project setting, or production resource was changed or accessed.

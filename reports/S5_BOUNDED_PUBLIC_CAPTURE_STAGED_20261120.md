# Sprint 5 bounded public capture source verification

The isolated stage adds the [bounded capture helper](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation/rippling_public_capture.py:214) and its [synthetic tests](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/tests/test_s5_rippling_public_capture.py). The existing parser, authority, candidate validator, admission, enrollment, slot and runner sources match their baseline bytes.

| Artifact | SHA-256 |
| --- | --- |
| `rippling_public_capture.py` | `4fec8b71709706d024a175dad240b82290ab23bcfbb591521bf7e9b27313ce2a` |
| `test_s5_rippling_public_capture.py` | `1b25dbe9004276b31ff23d672588c909fa5d0e20ec58a63c79715a81dab88b23` |
| Unchanged listing and detail oracle | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| Unchanged public authority parser | `5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57` |
| Unchanged candidate replay validator | `e1e5cfb34c01694f9722169343d9fe19417c16623758de79cb74c17685aca25e` |

The helper takes an application-owned slot binding and reserved boot/wall/elapsed window, the two exact Company projections, a policy matching the enrolled collector digest, an owned ledger and a reviewed transport dependency. It requests only the approved employer and canonical board routes, the non-followed PDW 308 alias, sequential listing pages and details for verified canonical UUIDs. Every GET requires the durable begin acknowledgement before transport. Each successful raw response is bound to the exact durable completion record and final ordered readback. The helper refuses prior ledger work, malformed or changed authority and board evidence, stale or ambiguous HTTP freshness, missing detail, expiry, excess requests or bytes, and an empty inventory pending a separately approved zero policy.

The result contains existing `rippling-public-capture-v1` replay bytes, a canonical manifest, and original ordered header and entity bytes for each exchange. The capsule budget includes the raw bytes, replay JSON and manifest. The response policy binds maximum entity bytes, maximum HTTP age, future Date skew and the approved transport-policy digest. HTTP freshness is checked at each response completion. A later issuer remains responsible for freshness at final approval, verifying the real transport-policy identity, durable owner custody, and committing the capsule. The injected transport must enforce the passed combined and separate byte limits and elapsed deadline during I/O. The helper itself has no transport, production wiring, application writes, or verdict authority.

The fixture replayed 21 Forterra and one PDW postings through the existing candidate validator and normal provider dispatcher. The 31 synthetic exchanges had durable begin and completion evidence, two ordered listing reads per company, full descriptions, duplicate ordered headers, and the original non-followed alias entity. The candidate replay's existing I/O guard saw zero prohibited actions.

**Verification.** All 23 focused cases passed. The combined synthetic collector, typed Rippling mismatch and issuance-slot regression passed all 207 tests in 13.00 seconds using the default interpreter, explicit isolated paths and bytecode disabled. No actual provider, production database, service, remote or Jetson operation was used.

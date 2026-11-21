# Independent QA — Sprint 5 public capture transport

Date: 2026-11-20

## Scope and pins

Read-only source review and disposable synthetic fixtures only. No live socket, DNS, network, credential, production path, or source edit was used.

- `dev/pre_release_validation/rippling_public_transport.py`: `1df2a46f9f0aff246a9e0b1c5a74a96bf3d012a5a861ff9253dc7646809c708a` — verified.
- `tests/test_s5_rippling_public_transport.py`: `dfff7790ef0221f3fed687d86166b6442a6edf306a59c0e3d82a73418479b7e6` — verified.

## Positive isolated-adapter result

```text
env PYTHONPATH=/tmp/jsh-s5-public-capture-transport.BCQkmMfW/dev/pre_release_validation:/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation:/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/tests:/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/src python3 -m pytest -q tests/test_s5_rippling_public_transport.py
# 47 passed in 0.47s
```

Source review and the passing synthetic tests support the narrow transport properties:

- exact reviewed URL shapes only; no URL host rewriting, redirect following, DNS lookup, proxy lookup, or second connection;
- one nonblocking numeric-address TCP connection, TLS hostname/SNI verification, TLS 1.2 floor, and HTTP/1.1-only ALPN acceptance;
- one serialized `GET`, identity encoding request, no request retry; 
- retained raw ordered HTTP/1.1 header bytes while redirect/refresh and status chains are independently checked;
- explicit content-length or strict chunk framing; rejection of close-delimited, duplicate/conflicting length, trailers/extensions, malformed short frames, and unread entity exit;
- CLOCK_BOOTTIME deadline checks around each I/O wait/call and after descriptor cleanup; separate header/entity/combined bounds plus dedicated chunk-framing bound.

## Blocking integration issue: declared helper pin is not enforced

`TRANSPORT_HANDOFF.md` declares the accepted `rippling_capture.py` dependency as:

```text
6a8ff763c69f7aeebf3da0f60b85a2d7deba17c9f2b20677d9a5e75db58bd571
```

The transport imports `rippling_capture`, `rippling_public_authority`, and `validate_candidate` by bare module name. It has no dependency-location or digest verification. The isolated helper used to make the focused test suite runnable was loaded from a disposable `/tmp` dependency tree and had observed SHA-256:

```text
46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d
```

The saved probe confirms that mismatch:

```text
env PYTHONPATH=... python3 -m pytest -q /tmp/jsh-s5-public-capture-transport-independent-qa.py
# 1 passed in 0.01s (negative dependency-pin probe)
```

Therefore the 47-pass result verifies the adapter only against that explicitly supplied disposable dependency set, not the handoff-declared accepted helper. A different same-name module can change `CaptureError`, route constants, caps, status parsing, or collector integration without changing either reviewed pinned file.

## Recommendation

Accept only the adapter's source-level design as **conditionally suitable for isolated fixture evaluation**. Do not accept it as integrated transport or activate it until a staged, independently hash-pinned dependency capsule is supplied and the suite is rerun from that verified capsule. The adapter should either receive reviewed dependency objects explicitly from a verified launcher/capsule or verify a predeclared immutable dependency bundle before use; bare ambient imports are not sufficient for the stated exact-source assurance.

No message display flag or output truncation occurred during this QA.

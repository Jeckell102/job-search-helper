# Release custody extraction — independent source gate, 2026-11-21

**HOLD this exact pin for one narrow exception-semantics regression.**
The provider-neutral import works, and all 77 focused tests pass. The only
identified required repair is preserving the original decode error's suppressed
parser exception context. No broader custody or release gate failure was found.

Author stage: `/tmp/jsh-s5-release-qualification-custody.20261121`.
Independent source/test copy: `/tmp/jsh-s5-custody-independent.a_qk_9ri`.

| File | Reviewed SHA-256 |
| --- | --- |
| `private_file_custody.py` | `e57484449665ebd14c00fe1e4a9ec3f6bf4bc9907126fe608a9f690937e5142d` |
| `release_qualification.py` | `e91a7015f457b4acfb514ec3952f4173699962e7a2712cf43e088cd1a2005613` |
| `ordinary_raw_capture.py` | `7eb399c16bd2661f3111e86c410e5d2d9f6208b762046057b4863f783dc5ead2` |
| `tests/test_release_qualification_custody_import.py` | `a9dd3e29b4d9362b227bc184ff36c9c3625ba4c0a200fb738681b8aa89c4fd84` |

Application basenames are under `src/job_search_helper/`.

## Exact finding and fix

The original `_decode` at baseline SHA
`b038adffbdf2bac9811806a8aaecf2cb816cebeb2bcce73037447670503ee571`
ends its parser-exception branch with
`raise CaptureError('invalid_capture_metadata') from None`. The extracted
`private_file_custody.decode` instead calls `_fail(error_type, ...)` inside
that branch, so the parser context becomes visible in an ordinary traceback.

An independent comparison loaded the exact original module from the saved
source snapshot and the candidate in a disposable Python process. For
`_decode(b'{')`, both return `CaptureError` with `invalid_capture_metadata`,
but the original has `__suppress_context__ == True`; the candidate has False.
Both contexts are `JSONDecodeError`. This changes established CaptureError
behavior even though the message and type match.

Smallest correction: keep the existing typed-error re-raise, then use
`raise error_type('invalid_capture_metadata') from None` in the decode
exception handler. One focused regression should compare type, code and
suppression for malformed metadata. Do not alter filesystem or release policy.

## Confirmed checks

Compared the original custody functions and release gate to the extraction.
The device/inode identity, absolute component-wise no-follow lookup, directory
owner/0700, regular-file owner/0600/single-link requirement, mode/size/mtime/ctime
stamp, size-limited no-follow read, pre/post descriptor stat and named-file
recheck are retained. The release gate still duplicates the supplied descriptor,
matches physical root identity, verifies the approved exact receipt hash and
canonical contents, checks every qualification field, and rechecks the named
receipt and root after validation. Capture wrappers still pass CaptureError.

**77 focused tests passed in 1.56 seconds** using explicit Python 3.11.18
with isolated flags, private sources/tests and a network-denying audit hook:
release qualification, custody import and ordinary raw capture. The fresh
isolated import subprocess blocks `ordinary_raw_capture` resolution and loads
the neutral helper, so it does not require the Rippling capture dependency.

No source edits were made by this reviewer. No production, application data,
Google, Jetson, network, service or release operation was performed. This is
a source gate; the exact Amphenol deployment composition remains root-owned.

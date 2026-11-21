# Release custody suppression recheck — 2026-11-21

**ACCEPT the corrected extraction; the sole prior HOLD finding is closed.**
The original `INDEPENDENT_QA.md` remains intact. Its 77 focused passing tests
and reviewed unchanged custody/release behavior remain scoped to that review.

Corrected stage: `/tmp/jsh-s5-release-custody-correction`.

| File | Verified SHA-256 |
| --- | --- |
| `private_file_custody.py` | `9f1ec341e3556aaf3a4460781c1cff78f29dae720c673add2fb64416d924cdce` |
| `tests/test_release_qualification_custody_import.py` | `faf8875356ec4590455a848eba62f355808eedcdfc32181462d28f923f891cba` |
| `release_qualification.py` (unchanged) | `e91a7015f457b4acfb514ec3952f4173699962e7a2712cf43e088cd1a2005613` |
| `ordinary_raw_capture.py` (unchanged) | `7eb399c16bd2661f3111e86c410e5d2d9f6208b762046057b4863f783dc5ead2` |

Application basenames are under `src/job_search_helper/`.

One focused original-versus-corrected reproduction ran with explicit
Python 3.11.18 and isolated flags. Calling `_decode(b'{')` on both exact
modules produced their own `CaptureError`, message `invalid_capture_metadata`,
`__suppress_context__ == True` and underlying `JSONDecodeError`. The correction
is the exact original `raise ... from None` behavior. The added subprocess
assertion checks the neutral helper's suppression; its source was reviewed.

No additional tests or unrelated checks were performed. No source edits,
production, network, Google, Jetson, service or native release operation
occurred. This closes the source finding; deployment remains separate.

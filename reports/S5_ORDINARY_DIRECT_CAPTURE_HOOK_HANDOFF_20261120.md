# Sprint 5 private direct Rippling capture hook

**Disposition — independent QA accepted the isolated source for offline integration against the pinned continuation baseline.** The coordinator owns staging, enrollment, the measured worker, and acceptance of the combined candidate. Live use remains outside this handoff.

## Source and policy pins

The input tree is `/tmp/jsh-s5-ordinary-continuation.0wnbkEVB`. Its `shared_boards.py` was `4409757864804785dbc85b8fa1be988235be7ac5f075e00ccc89cd29e0c20f66`. [Baseline input checksums](/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO/checkpoints/BASELINE_INPUT_SHA256SUMS) pin `ats.py`, `browser_scraper.py`, the pending schema, the accepted custody input, and the existing typed-view regression. The regression was assembled in a disposable continuation copy. The implementation overlay is `/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO`.

| Owned path relative to overlay | SHA-256 |
| --- | --- |
| `src/job_search_helper/ordinary_capture_context.py` | `1b4b776af082839cd9cea4518edc8b1ef325c307d5ffc3e703fd24e66347a4a1` |
| `src/job_search_helper/shared_boards.py` | `71518f340ee616fab63d9dd58ebdc9c103eb5294a3fc2fcd9e70fca4fdd31ddf` |
| `tests/test_s5_ordinary_direct_capture_hook.py` | `378f3c0068856aed01817517a4fc3dcd2d06328e489650f1a7d108c403f751a5` |

The callable `capture_policy_sha256()` returns `6194f04b9112c7677b1502b4fdf68fd7d8ba938de5a00dd52c8242423facddb3`. It supersedes the interim checkpoint pin after the TLS implementation fixed trust to compiled system CA paths. The independent measured source digest must still commit the code. [Exact source manifest](/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO/checkpoints/QA_SHA256SUMS)

## Integration contract

The measured owner provisions the accepted private custody ticket and imports `bind_direct_capture` and `capture_policy_sha256` from `.ordinary_capture_context`. Enroll the reservation with the public callable's current digest. Bind the ticket once around the exact synchronous fetch in its owning thread. The one-shot binding checks the exact canonical configured URL. It expires with the lexical scope, including for copied contexts. The owner retains responsibility for the final Inventory and seal after browser fallback precedence. A typed mismatch with no attested response remains a custody hold.

The hook attests only the internally selected original built-in `Transport` at canonical Rippling page zero. It reuses the existing read, retry budget and parser. The scoped HTTPS GET does not follow redirects or use ambient proxies, requests identity encoding, requires peer and host verification using compiled system CA paths, and disables TLS key logging. It supplies no bytes on redirects, ambient CA overrides, synthetic or injected transports, an altered or redirected response, later pages, rereads or browser navigation. At the exact typed mismatch the hook offers the original `HTTPResponse.body` and metadata privately. Generic Inventory and F6 receive no additional fields. The browser fallback, normal opener and final-selection behavior retain their existing routes. [Frozen interface](/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO/checkpoints/INTERFACE.md)

## Reproduction

Focused fixtures passed **26**, exit **0**. This path intercepts urllib's HTTPS handler below opener selection, blocks networking, exercises real custody reservation and sealed readback against disposable bytes, and checks final browser precedence. [Focused log](/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO/checkpoints/focused.log)

```bash
cd /tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO
sha256sum -c checkpoints/QA_SHA256SUMS
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o 'pythonpath=/tmp/jsh-s5-ordinary-continuation.0wnbkEVB/src' \
  --basetemp "$PWD/checkpoints/pytest-replay" -q --tb=short \
  tests/test_s5_ordinary_direct_capture_hook.py
```

The continuation regression passed **240**, exit **0**. The disposable copy includes the accepted custody module, the typed mismatch tests and normal ATS, discovery, shared-board, locations, routing and ordinary-worker fixtures. Its pytest process refuses socket connect and resolver events. The existing bootstrap subprocess fixture stops at its local qualification gate using disposable SQLite stores. [Regression log](/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO/checkpoints/regression.log)

```bash
cd /tmp/jsh-s5-ordinary-hook-regression.S4kuFmjZ
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o 'pythonpath=src . tests' --basetemp "$PWD/pytest-replay" -q --tb=short \
  tests/test_s5_ordinary_direct_capture_hook.py tests/test_s5_typed_rippling_mismatch.py \
  tests/test_ats.py tests/test_discovery.py tests/test_shared_boards.py \
  tests/test_rippling_locations.py tests/test_source_routing_recovery.py \
  tests/test_s5_ordinary_worker_handoff.py
```

## Independent review and remaining integration

**Independent verdict — ACCEPTED** for the exact source and policy pins above. Independent QA verified the manifest and loaded the pinned continuation dependencies, reran all **26** maintained fixtures and passed **36** independent observations, exit **0**. Probes covered the verified direct opener during a transient CA override, original-transport provenance, redirects and retries, the ordinary path with custody unavailable, lexical and thread scope, and browser precedence and F6 containment. Fixtures intercepted urllib below opener selection and did not establish a live TLS handshake. The independent report includes commands, exit results and probe pins. Its SHA-256 is `548009192a6a35ddb2597d3bc99a6f8791061d5272bebf2d2d7fb3dc4d0a8d17`. [Independent QA report](/tmp/jsh-m5-validation-independent.pKaySTku/direct-capture-hook-qa.lAfMrU0d/continuation-rerun.BuogH2SS/DIRECT_CAPTURE_HOOK_FINAL_QA.md)

No production source, company record, queue, Sheet, Jetson service or GitHub state was touched. No public collection or live release qualification was performed. The coordinator next imports the two source files and focused test, verifies the admission source digest and policy pin, and checks the exact composed worker path with private custody.

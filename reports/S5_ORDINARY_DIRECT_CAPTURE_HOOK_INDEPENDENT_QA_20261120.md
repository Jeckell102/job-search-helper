# Independent QA of the ordinary Rippling direct capture hook

**Accepted for the exact isolated direct-capture hook with the pinned continuation tree.** The review used an actual urllib adapter and handlers with synthetic responses and all socket activity barred. Runtime enrollment, measured launcher integration, live TLS/HTTP, private capture ownership at the application boundary, and deployment remain separate.

| Reviewed artifact or policy | SHA-256 |
| --- | --- |
| QA manifest | `4a998eac5e866f86e2f5751d8a1678591e4469820bf81f74a2860281162f99eb` |
| `src/job_search_helper/ordinary_capture_context.py` | `1b4b776af082839cd9cea4518edc8b1ef325c307d5ffc3e703fd24e66347a4a1` |
| `src/job_search_helper/shared_boards.py` | `71518f340ee616fab63d9dd58ebdc9c103eb5294a3fc2fcd9e70fca4fdd31ddf` |
| `tests/test_s5_ordinary_direct_capture_hook.py` | `378f3c0068856aed01817517a4fc3dcd2d06328e489650f1a7d108c403f751a5` |
| `checkpoints/INTERFACE.md` | `01833750d8917d7953cba533cbe4047b43d7b971aeedf9925cbc26355c748d3b` |
| Direct capture policy | `6194f04b9112c7677b1502b4fdf68fd7d8ba938de5a00dd52c8242423facddb3` |
| Imported accepted custody module | `b038adffbdf2bac9811806a8aaecf2cb816cebeb2bcce73037447670503ee571` |
| Continuation `ats.py` | `92a1e43194f02201089e81f5a891fb368f44865f50aeab351d8281fdd0290a20` |
| Continuation `browser_scraper.py` | `d24ae2fe07c26186ff9edbe99140dba6f65aae93a0269b769a1c6cd74b13250c` |
| Continuation `engine.py` | `11ca08ff5153a1ce0ead269a2c25226753300524d5e348fa03cb5e97c145780b` |
| Continuation `ordinary_verification_pending.py` | `678b390e656ac5925a932df41f7569ebc9f825286cf94a3370cb6d5622239f25` |

All four implementation manifest entries matched. The maintained suite passed 26 tests in 2.00 seconds, and the independent runs passed 36 observations. The dependency-origin check verified the four imported continuation files and recorded their hashes. The independent logs were byte-identical to the earlier checkpoint while using the pinned continuation source. The only positive private offer from source dispatch used the internally created original Transport and canonical page-zero request. The exact-class explicit instance, subclass, falsy injected subclass, substituted factory, alias route, noncanonical query, mismatched final URL, foreign ticket route, wrong provider label, and employer discovery supplied no private body. Later pagination and final reread supplied no capture. The existing page-zero retry used the same verified scoped client, and only the final successful response body matched the captured bytes.

The scoped urllib request avoided the configured proxy and used peer/hostname verification with no TLS key logging. Ordinary unbound dispatch retained its regular opener, including ambient proxy behavior in the fixture, and completed with the optional custody package unavailable. The scope declined to attest while either process CA override variable was present. A transient CA override during trust setup left the explicit compiled trust paths unchanged and permitted the correctly scoped fixture capture. This host's compiled trust directory is loaded lazily, so the QA verified the actual loader arguments and context verification properties without assuming an eagerly populated certificate count. Actual urllib redirect handling did not follow a 308, and HTTP denial or a 200 response carrying a redirect indicator provided no body for custody.

Cross-thread copied and stale contexts could not claim a ticket. A current same-thread lexical copy could claim one time, exceptional teardown revoked stale copies, and nested distinct bindings restored the outer ticket. One-use binding and policy mismatch held before fetching. The existing browser wrapper selected the exact direct bytes only when the different browser entity corroborated the same mismatch. Changed tenant, complete, blocked, transient, and pending browser results left no sealed body. The positive receipt hash bound the unchanged F6 payload. Raw bytes and the private capture path were absent from Inventory, F6 and tested summaries. No socket, real provider, browser, workbook, State/Jobs, queue, production source, or source overlay was accessed for modification.

### Reproduction

From `/tmp/jsh-s5-ordinary-direct-capture-hook.kmeMkiQO`:

```sh
sha256sum -c checkpoints/QA_SHA256SUMS
qa_tmp=$(mktemp -d /tmp/jsh-s5-direct-hook-independent.XXXXXXXX)
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o 'pythonpath=/tmp/jsh-s5-ordinary-continuation.0wnbkEVB/src' -q --tb=short \
  --basetemp "$qa_tmp/pytest" tests/test_s5_ordinary_direct_capture_hook.py
```

From this report's private directory:

```sh
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_transport.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_context_browser.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_tls_load_window.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_optional_default_off.py
```

All commands exited 0. Results are retained in `maintained.log`, `transport.log`, `context_browser.log`, `tls_load_window.log`, `optional_default_off.log`, and `module-provenance.log`. The [previous QA report](/tmp/jsh-m5-validation-independent.pKaySTku/direct-capture-hook-qa.lAfMrU0d/DIRECT_CAPTURE_HOOK_FINAL_QA.md) is retained as the pre-continuation checkpoint.

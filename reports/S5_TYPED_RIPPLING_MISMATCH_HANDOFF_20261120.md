# Sprint 5 typed Rippling tenant observation

2026-11-20 18:31 EST

**Staged and fixture-verified.** Overlay is `/tmp/jsh-s5-typed-rippling-mismatch.8Y5skdi8`. This supersedes the initial pins after independent QA reported typed-only malformed-input and browser-provenance gaps. Its three source files are based on the accepted checkpoint/custody composition and preserve that base's verified-zero fields. No production source edits, live network calls, database copies, or deployment.

- `ats.py:90` defines the optional frozen `Inventory.rippling_tenant_mismatch` value. Use `.to_record()` for its exact five-field envelope and `validate_rippling_tenant_mismatch(record)` to read it back. The keys are `schema` (`rippling-tenant-mismatch-v1`), `configured_url`, `expected_slug`, `observed_slug`, and `response_sha256`.
- `shared_boards.py:475` and line 551 enforce one unambiguous active Next.js data script, duplicate-free JSON, a single foreign-tenant listing query with the explicit public flag, exact integer pagination and counts, and UUIDs with nonblank provider names. Competing listing queries, inert/duplicate scripts, non-JSON constants and late active challenge titles refuse typed evidence. The stricter parser runs only once the normal parser has already found an exact configured-page mismatch.
- `shared_boards.py:587` requires an exact integer HTTP 200 and the canonical URL on the initial page-zero response. Browser evidence also requires the original unredirected navigation response to be available and within the existing byte limit and its tenant to agree independently with the rendered page. The browser transport at line 1252 keeps ordinary rendering separate from this typed-only check. Missing, conflicting, oversized and challenge response bytes retain the ordinary partial result.
- `browser_scraper.py:898` preserves normal fallback selection. An incomplete browser result must corroborate the direct result's URL and tenant identities, and the wrapper retains the direct response digest. Browser-disabled direct dispatch can emit the typed observation independently. Complete, access, temporary and ambiguous cases carry no mismatch observation.
- The output remains an empty partial inventory with the same reason and no typed outcome failure. It is not serialized by the existing F6 inventory payload. Qualification and independent employer, candidate inventory and regression proof belong to the next lane. The red test's injected transport must pass `response_url=url` as the optional `HTTPResponse` keyword for its exact stale response.
- The installed qualification tuple needs to be measured from the composed fixture because the approved capability's source vector includes both `ats.py` and `shared_boards.py`.

## Tests and pins

The final focused suite passed **100** cases. The combined run added existing disposable ATS, browser fallback and Rippling location tests and passed **157** cases. Earlier broad runs exposed an incomplete test fixture copy and assertions that assumed one legacy reason for every inert element. The final command uses the intact staged fixture source and checks the existing legacy result for each case.

```bash
stage=/tmp/jsh-s5-typed-rippling-mismatch.8Y5skdi8
base=/tmp/jsh-s5-checkpoint-custody-composition.y8voh14Y
qa=/tmp/jsh-s4-dispatch-binding-qa.i45G33KN/tests
PYTHONPATH="$base/src" /home/chris/job-search-helper_old/.venv/bin/python -B -c \
  'import sys, pytest, job_search_helper; job_search_helper.__path__.insert(0, sys.argv[1]); raise SystemExit(pytest.main(sys.argv[2:]))' \
  "$stage/src/job_search_helper" -q -p no:cacheprovider --basetemp "$stage/test-work-with-regressions" \
  "$stage/tests/test_s5_typed_rippling_mismatch.py" \
  "$qa/test_rippling_locations.py" "$qa/test_browser_scraper.py" "$qa/test_ats.py"
```

```text
92a1e43194f02201089e81f5a891fb368f44865f50aeab351d8281fdd0290a20  src/job_search_helper/ats.py
4409757864804785dbc85b8fa1be988235be7ac5f075e00ccc89cd29e0c20f66  src/job_search_helper/shared_boards.py
d24ae2fe07c26186ff9edbe99140dba6f65aae93a0269b769a1c6cd74b13250c  src/job_search_helper/browser_scraper.py
943db953d13c9cb304ab3aa63fe5a5d2e0dc81eb90cbfff34dce45bdcd6b1663  tests/test_s5_typed_rippling_mismatch.py
```

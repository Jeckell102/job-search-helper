# Exact recovery pause executor — independent QA failure

Date: 2026-11-19

Affected candidate hashes:

- executor: `4e31db0b1cd8bcf4e88d2b7017361990e9df4e3b8f2e45bd4b5f77cffed6158d`
- tests: `c256af3d00904be8645c6bc05d0836a326dadcc6f38ab5290c9b77eae52013cd`

## Result

REJECT for activation. No live or production action was authorized.

### F1 — caller-selectable lock does not prove normal writer ownership

`execute_exact_recovery_pause(..., lock_path=...)` accepted any caller-selected
path. Independent QA held the fixture's intended normal `scraper.lock`, passed
a different lock path, and the executor still completed two remote commits and
finalized State as `Complete with exceptions`. The existing contention test
only contended on the same supplied path.

Repair: remove caller selection and derive the exact normal scraper lock from
file-backed `State.path` and `scraper_lock_name()`. Missing or in-memory State
must fail before State, inbox, journal, apply-store, or remote access. Add a
real-normal-lock contention test and reject obsolete path injection.

### F2 — an oversized later entry can bypass the chunk-byte limit

`_chunks` rejected an oversized entry only when the current chunk was empty.
When a small entry preceded an individually oversized entry, it yielded the
small chunk and then retained the oversized entry as a new chunk without a
second size check. Independent reproduction yielded payload byte sizes 76 and
500096 while `MAX_CHUNK_BYTES` is 500000.

Repair: validate every individual entry before adding or rolling a chunk, add
the small-then-oversized adversarial case, and assert every yielded payload is
at most 500000 canonical UTF-8 bytes.

## Passing evidence retained

Other reviewed boundaries were structurally sound: fresh phase-A journal
revalidation, full run freeze before the first remote write, exact candidate
coverage, active/unclaimed/cycle/scan-state guards, intent-before-write,
readback-only retained intents, preserved terminal holds, correct exception
counts, selected-row access, and no global synchronization path. Focused pause
tests passed 34 tests in 1.71 seconds; the adjacent recovery regression passed
204 tests in 28.40 seconds. These passing results do not waive F1 or F2.


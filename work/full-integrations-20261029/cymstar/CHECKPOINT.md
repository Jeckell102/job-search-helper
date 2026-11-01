# CymSTAR checkpoint — 2026-11-01

- Company: CymSTAR (`COMP-0333`)
- Official source: `https://www.cymstar.com/careers/career-listing`
- ATS: employer-scoped ADP Workforce Now (`cid=d1bbed86-b8f3-4234-bd7b-d96e7853d0dc`, `ccId=19000101_000001`)
- Adapter/routing: repaired the exact source mapping and allowed ADP's harmless `client` display parameter.
- Focused tests: 26 passed across CymSTAR, ADP, and source-repair suites.
- Installed normal pipeline: two consecutive rereads failed at ADP listing page 1 with the same bounded network/timeout error.
- Stable installed job count: not established.
- Terminal disposition: blocked; do not count complete until live ADP access is restored and two stable rereads succeed.
- Evidence: `evidence/installed-validation-20261101.json`

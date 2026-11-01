# Komatsu checkpoint — 2026-11-01

- Company: Komatsu (`COMP-0240`)
- Official careers source: https://www.komatsu.com/en-us/careers
- Verified ATS: SAP SuccessFactors / Jobs2Web at https://komatsu.jobs/viewalljobs/
- Adapter: the branded board's public `/services/recruiting/v1/jobs` endpoint, followed by pinned public detail pages.
- Focused tests: 30 passed.
- Installed normal pipeline reread 1: `partial`, 0 jobs; the API published a result without a stable requisition ID.
- Installed normal pipeline reread 2: `partial`, 0 jobs; the same blocker recurred.
- Terminal status: blocked, not complete. A stable inventory count was not established.
- Evidence: `work/full-integrations-20261029/komatsu/evidence/installed-validation-20261101.json`

Shared completion ledgers were intentionally left unchanged.

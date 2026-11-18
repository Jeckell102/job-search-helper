# Installed scraper workflow update: November 18, 2026

These five files back up the tested update installed in the existing
`job-search-helper_old` checkout. They are source copies for that checkout,
not a standalone application or changes to the newer application on `main`.

The normal start command completes scraping and Google Sheets synchronization
before resolving Codex, checking login, reading the live AI Prompt, checking
model availability, and automatically starting FIRST PASS. If AI access fails,
the completed scan remains saved at `REVIEWING` / `PAUSED_NOT_COMPLETE`.
`./job-search-helper resume` continues review without another scrape.

The explicit pipeline `check` command still verifies both collection and AI
prerequisites. Live prompt verification, exact review ownership, publication
checks, and managed completion verification remain in place.

Validation: 47 offline tests passed against the installed source, covering
workflow ordering, quota failure and resume, missing/invalid Codex, public
command routing, runtime discovery, and existing completion safeguards.
No live scrape or AI review was started for validation.

Local originals were preserved under
`.state/source-backups/scrape-before-ai-20261118-1207/` in the old checkout.
Credentials, runtime databases, review results, and live prompt content are
excluded from this backup.

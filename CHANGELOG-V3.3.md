# v3.3 changes

- Removed OpenAI API calls from normal runtime.
- Added `job-search-scraper` one-command launcher.
- Kept `job-search-reviewer` only as a compatibility alias to the scraper.
- Scraper performs deterministic title rejection and clear below-$120k salary rejection locally at $0 AI cost.
- Added Work-readable Job History fields: Source Hash, Salary / Range, Work Arrangement, Job Description.
- Added one-time migration/backfill script.
- ChatGPT Work reviewer uses Google Drive / Google Sheets directly; no local job queue or local AI decision files.
- Work does title-first review and only reads the description when the title survives.
- Work copies Source Hash to Description Hash after a completed substantive review, so future scans can skip unchanged jobs without needing Work to edit Current Snapshot.
- Scraper self-heals Current Snapshot after it sees that the current Source Hash has already been reviewed.

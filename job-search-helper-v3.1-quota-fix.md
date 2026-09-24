# v3.1 Google Sheets quota fix

The observed crash was a Google Sheets API 429:
`Read requests per minute per user` exceeded the 60/minute quota.

## Root cause
The direct-Sheets reviewer and scraper are separate processes. In v3:
- every `repo.read()` fetched spreadsheet metadata and then grid data;
- an empty reviewer loop read Job History, Scan Cycles, and Job History again;
- after scraping, the coordinator also reread Job History every 3 seconds.

Together those reads could exceed Google's per-user quota.

## v3.1 changes
- Spreadsheet metadata is cached instead of fetched for every read.
- Metadata cache is invalidated only when a structural write changes dimensions/tables.
- Each Google repository process is paced at 2.5 seconds between API requests.
- Read-only requests use bounded Google-client retries for 429/5xx responses.
- AI empty-queue polling defaults to 10 seconds.
- The AI worker reuses the queue state from its existing Job History read rather than reading Job History twice.
- The immediate full-sheet reread after claiming a review was removed.
- The final decision still performs a fresh Job History validation before writing.
- After scraping completes, the coordinator waits for the AI worker process instead of polling Job History every 3 seconds.

## Install
Preserve `.env`, `.state`, `.secrets`, `credentials.json`, and `.venv`, then overlay the archive.

After updating, the normal command remains:

`./job-search-reviewer start`

The current unfinished cycle should resume automatically.

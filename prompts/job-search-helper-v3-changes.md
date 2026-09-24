# Job Search Helper v3 — Direct Google Sheets Workflow

## Architecture
- Google Sheets Job History is the authoritative job/review database.
- No local job queue and no local AI decision files.
- `.state` retains cycle/checkpoint control only; scraped job payloads are scrubbed before persistence.
- Legacy rows in the local SQLite `reviews` table are purged at startup.

## Job History columns added
- Review Status
- Review Started At
- Decision
- Fit Level

Review Status values:
- Needs Review
- In Progress
- Reviewed
- Manual Review

Decision values:
- Accept
- Reject
- Needs Info

Fit Level values:
- Strong
- Possible
- Stretch

## Concurrency
1. Scraper discovers a new/materially changed job and writes it to Job History with `Review Status = Needs Review`.
2. Reviewer claims exactly one job by writing `In Progress` and `Review Started At`.
3. While a row is `In Progress`, scraper-originated Job History changes are skipped at the final fresh-read commit boundary, including Last Checked / Last Seen updates.
4. Claims older than 30 minutes may be reclaimed.
5. Reviewer commits its result directly to Google Sheets.
6. On the next scan, the scraper can compare the reviewed posting against current source evidence normally.

## AI stages
### Stage 1
Default model: `gpt-5.6-luna`
Input: job title only.
Output: `review` or `reject`.

Explicit title-screen reject examples include:
- Systems Engineer
- Staff Engineer / Senior Staff Engineer
- Electrical Engineer
- Mechanical Engineer
- Materials Engineer
- Software/Firmware Engineer
- Systems Test / Test Automation roles
- unrelated finance/HR/legal/clinical/entry-level families

Target-function titles such as Staff Solutions Engineer, Field Applications Engineer, Field Engineering, integration, solutions, product/technical program, support, training, and deployment advance to full review.

### Stage 2
Default model: `gpt-5.6-sol`
Input: the full posting fields/description for one job only.
Output: Accept + Strong/Possible/Stretch, Reject, or Needs Info.

No résumé recommendation is produced.
No mandatory-clearance column is stored. Mandatory clearance is simply a hard rejection rule.

## Restart behavior
Normal command remains:

```bash
./job-search-reviewer start
```

It resumes the latest unfinished cycle or starts a new full cycle when none is unfinished.

## Environment
Recommended additions:

```text
OPENAI_TITLE_MODEL=gpt-5.6-luna
OPENAI_REVIEW_MODEL=gpt-5.6-sol
AI_REVIEW_POLL_SECONDS=3
AI_REVIEW_MAX_RETRIES=5
AI_REVIEW_STALE_MINUTES=30
```

## Workbook update
The Job History sheet was extended from 24 to 28 columns and its filter range was extended to include the new fields. The Search Config hard-title-filter entry was updated to describe title-only triage and to explicitly reject Systems Engineer while preserving target-function engineering titles.

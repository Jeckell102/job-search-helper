# Scrape and FIRST PASS

Python starts the existing job scraper, verifies completion and Google Sheets
publication, then asks **GPT-5.6 Luna with medium reasoning** to assess claimed
titles. It uses the existing signed-in Codex CLI. No Jetson or OpenAI API key is
required. The computer must stay awake and online.

## Commands

From the installed job-search-helper directory:

```sh
./job-search-pipeline check
./job-search-pipeline run
./job-search-pipeline status
./job-search-pipeline run --resume
```

`check` verifies local configuration, both saved Google authentication grants,
read access to current Sheet headers, live AI Prompt access through Codex's Google
Drive connector, and the exact requested model. It does not start a scrape, take
review claims, or write Sheet cells. It saves private diagnostic logs locally.
Pending uploads and conflict counts are reported separately from connectivity.

`run` starts a fresh full-company scan. It uses five fetch workers by default;
set `--fetch-workers 10` if desired. It assesses up to 25 titles per batch; use
`--batch-size 1` through `100`. It stops after FIRST PASS. It does not start
SECOND or THIRD PASS or schedule future runs.

`run --resume` continues this controller's unfinished workflow. A completed
scrape is not repeated. A completed workflow is a no-op on resume. To start a new
scan after completion, use plain `run`. An interrupted scan resumes its own
saved cycle. A separate manually launched scrape is never adopted implicitly.

## What establishes completion

- The controller binds to the newly created cycle, never an older completed one.
- The cycle must be `Complete` or `Complete with exceptions`. Exceptions remain
  recorded; failed boards are not treated as complete inventories.
- SQLite must be ready, with zero pending rows/cells and no last sync error.
  A bounded normal sync retry runs if needed. Conflicts are never cleared or
  overwritten. Existing historical conflicts do not block an otherwise clean
  publication state, but are recorded in the workflow journal.
- The live Google Drive **AI Prompt** is fetched again immediately before each
  review start/resume. The controller extracts actual connector response text;
  a model summary or cached local prompt cannot satisfy this requirement.
- Python invokes the managed reviewer for claims, lease renewal, submissions,
  publication, and finish. Luna makes each individual assessment. Descriptions,
  employer, location, pay, and URLs are omitted from FIRST PASS model input.
- Every result is matched to the exact claimed identity. A fresh managed check
  before submission handles withdrawn/manual choices and changed claim tokens.
- Only a live managed `DRAINED` or `DRAINED_WITH_EXCEPTIONS` finish completes the
  workflow. An empty batch or successful model exit is insufficient.

The review covers the existing eligible FIRST PASS queue, including backlog, as
defined by the current AI Prompt. It is not restricted to new jobs from this scan.

## Progress and recovery

Progress is printed at stage changes and once a minute while commands run.
Private logs, prompts, results and `workflow.json` are stored under the configured
scraper state directory's `scrape-first-pass/`. `status` displays the durable
workflow, last submission/finish receipt, errors and most recent cycle.
Keep these files out of GitHub; only source, tests and documentation belong there.

Ctrl+C or SIGTERM stops the current child process, records `PAUSED_NOT_COMPLETE`,
and attempts to pause only this workflow's reviewer. Resume with the same command
above. After an uncertain submission, existing managed decisions are reused;
remaining current claims are reconciled before any retry. A lost start receipt
blocks for inspection instead of silently creating a duplicate worker.

The controller lock remains inherited by a child if the controller is killed,
so another controller cannot start over a still-running child. Existing scraper
and Sheet writer locks remain under the original managed tools. Never remove them.

Authentication, model, connector, stale-policy, identity and publication failures
stop the workflow with logs and a resume point. There is no model fallback.
Unchanged waiting states are checked once per minute, up to 30 checks by default;
then the workflow pauses for a later resume. Scraping has a 48-hour default limit.

The model runs in Codex's read-only sandbox. Python performs authorized data
updates exclusively through the existing managed reviewer. This avoids granting
the assessment model direct Sheet-writing responsibility. No system-wide Codex
settings, scraper rules, or title blacklist are changed.

## Installation and tests

Install this folder as `scrape-first-pass/` within the existing scraper project,
and install the accompanying `job-search-pipeline` launcher in its root.
Use the installed scraper's Python environment; the controller itself needs
only Python's standard library, Codex, and the existing scraper/reviewer.

```sh
python3 -m unittest discover -s scrape-first-pass -p 'test_*.py' -v
```

The CLI's Google Drive plugin connection must be available in a normal terminal
session. `check` confirms it; no desktop task ID is required by this controller.
Codex uses saved account authentication and its normal account usage limits.

References: [Codex scripted execution](https://learn.chatgpt.com/docs/non-interactive-mode),
[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

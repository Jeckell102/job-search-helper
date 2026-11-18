# Scrape, then ask the AI to do FIRST PASS

After the scraper finishes and Google Sheets synchronization is verified, Python
launches **one persistent Codex CLI task using GPT-5.6 Luna with medium reasoning**.
The task begins with:

> Read "AI Prompt" in my Google Drive and do a FIRST PASS, following its current instructions.

Codex reads the live document through the Google Drive connector and manages the
entire review itself using the installed managed reviewer. Python does not choose
batches, supply title judgments, or duplicate the review rules. The AI Prompt
remains the source of review instructions. Only FIRST PASS is requested.

## Commands

Both public scraper entry points now use the same packaged workflow. Your normal
command starts scraping, synchronizes saved results, and launches FIRST PASS:

```sh
./job-search-helper start --fetch-workers 15
```

`start` always begins a fresh full scrape, even when an older FIRST PASS was
paused. It creates a new workflow and keeps the older workflow, review receipts,
and already-published decisions intact. The new workflow records the previous
workflow's path. FIRST PASS starts only after the new scrape and publication
gate complete. An active controller or scraper still prevents a duplicate run.

Normal starts check only scraper and Google Sheets prerequisites before collecting
jobs. Codex installation/login, live AI Prompt access, and model availability are
checked **after** the scrape finishes and Sheets synchronization passes. Missing
Codex, exhausted usage, or an unavailable Drive connector pauses FIRST PASS at
`REVIEWING` with `PAUSED_NOT_COMPLETE`; the completed scrape stays saved. Use
`./job-search-helper resume` once access is restored to continue review without
scraping again. The AI still reads the full current AI Prompt before reviewing.

To continue the latest workflow at its saved step instead:

```sh
./job-search-helper resume
```

If that workflow already finished scraping, `resume` continues its FIRST PASS
without scraping again. `start --resume` remains a compatible spelling.

`./job-search-scraper start` follows the same path. All scraper options are
forwarded to a private scan worker; the worker cannot recursively start the
workflow. Maintenance and help commands do not launch AI.


From the installed job-search-helper directory:

```sh
./job-search-pipeline check
./job-search-pipeline run
./job-search-pipeline status
./job-search-pipeline run --resume
```

The explicit `check` command verifies saved Codex authentication, both Google grants, Sheet header
access, live AI Prompt access, and the exact requested model. It does not start
a scrape or review, take claims, or change Sheet cells.

`run` starts a fresh full-company scrape with five fetch workers by default.
Use `--fetch-workers 10` if desired. It waits for the owned cycle to reach
`Complete` or `Complete with exceptions`, then verifies zero pending upload
rows/cells and no sync error. Normal bounded synchronization retries may run.
A completed scan whose only failure is final Sheets synchronization proceeds to
the bounded publication retry step. Other scraper errors still stop the workflow.
Unresolved publication blocks the AI handoff. One-sided recognized Fit Review
changes in Sheets are imported only if the local rating is unchanged and has no
pending or uncertain delivery. Concurrent rating changes remain conflicts.

The AI task runs in the scraper project with workspace write permission and
network access for its existing Google tools. It uses ordinary sandboxing, keeps
Google connectors enabled, and cannot request unattended privilege escalation.
No system-wide Codex settings are changed. Missing access pauses the workflow.
Fresh and resumed AI tasks receive the same explicit sandbox, network, model,
and approval settings after the applicable Codex subcommand.

The handoff asks Codex to read the full current AI Prompt immediately before
starting/resuming, own a single managed FIRST PASS run, save its actual run ID,
and follow the document through claims, assessments, submission, heartbeat,
publication, and finish. It does not launch SECOND or THIRD PASS or other agents.
The eligible first-pass backlog is included according to the live document.

## Codex executable discovery

The workflow uses an explicit `--codex` option first, then `JOB_SEARCH_CODEX`,
then `codex` on the terminal's `PATH`. If none is configured, it also checks the
installed Linux desktop package at `/usr/lib/chatgpt/resources/codex`. This lets
ordinary terminal starts use the existing signed-in Codex installation even when
the desktop app's extra search paths are absent. No shell-profile changes or
second installation are required when that executable is available. During a
normal run, executable discovery is deferred until the AI review step.

For a different installation, set `JOB_SEARCH_CODEX` to its executable path before
using the normal start command, or pass `--codex` to `job-search-pipeline`.
An invalid explicit override reports an error instead of selecting another copy.
Missing Python and missing Codex produce separate, actionable errors.
`job-search-pipeline status` reports resolved executable paths and remains usable
when automatic Codex discovery finds no installation.

## Completion and recovery

Python records the exact Codex session ID, logs, final response and review-owner
receipt under the configured state directory's `scrape-first-pass/` folder.
`./job-search-helper resume` (or pipeline `run --resume`) resumes that exact AI conversation and its own managed review run;
it never uses `--last` or guesses another task's run ID. A completed scrape is not
repeated. Resuming a completed workflow is a no-op. Plain `start` or pipeline `run`
always starts a new workflow. A completed scan from an older installation can be recovered explicitly without
rescanning:

```sh
./job-search-pipeline review --cycle CYC-EXACT-ID
```

Recovery requires the latest completed cycle and an idle scraper. Repeating it
resumes the same saved task, or does nothing if that task already completed.

An AI message saying "done" is insufficient. Python verifies a successful live
Google Doc read, the matching ownership receipt, and the managed runtime's drained
run/checkpoint with no ready claims, pending writes, pending publication, or active
upstream work. Exceptions must be reported as `DRAINED_WITH_EXCEPTIONS`.

Ctrl+C/SIGTERM stops the current child and preserves an incomplete workflow.
The controller attempts to pause only its own saved managed run. Uncertain
session/ownership receipts block for inspection rather than create duplicate
workers. Existing scraper and writer locks are preserved. Both scrape and review
have 48-hour default timeouts (`--scrape-timeout` / `--review-timeout`, seconds).
The computer must stay awake and connected. No schedule or recurring service is
created. No Jetson or API key is needed; saved Codex account authentication is used.

The implementation lives in `src/job_search_helper/scrape_first_pass.py`, with
`pipeline_probe.py` and the private `scrape_worker.py`. The old controller and
probe entry points are compatibility shims; they contain no second implementation.

Only source files belong in GitHub. Logs, live prompts, results, state databases,
and credentials remain local. Install the packaged modules, runner, sync changes, compatibility entry points,
and `job-search-pipeline` together. Keep `job-search-pipeline` executable.

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*pipeline*.py' -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_scrape_first_pass.py' -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_opportunity_fit_sync.py' -v
```

References: [Codex scripted execution and resume](https://learn.chatgpt.com/docs/non-interactive-mode),
[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

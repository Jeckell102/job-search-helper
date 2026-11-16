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

From the installed job-search-helper directory:

```sh
./job-search-pipeline check
./job-search-pipeline run
./job-search-pipeline status
./job-search-pipeline run --resume
```

`check` verifies saved Codex authentication, both Google grants, Sheet header
access, live AI Prompt access, and the exact requested model. It does not start
a scrape or review, take claims, or change Sheet cells.

`run` starts a fresh full-company scrape with five fetch workers by default.
Use `--fetch-workers 10` if desired. It waits for the owned cycle to reach
`Complete` or `Complete with exceptions`, then verifies zero pending upload
rows/cells and no sync error. Normal bounded synchronization retries may run.
Recorded conflicts are preserved; incomplete publication blocks the AI handoff.

The AI task runs in the scraper project with workspace write permission and
network access for its existing Google tools. It uses ordinary sandboxing, keeps
Google connectors enabled, and cannot request unattended privilege escalation.
No system-wide Codex settings are changed. Missing access pauses the workflow.

The handoff asks Codex to read the full current AI Prompt immediately before
starting/resuming, own a single managed FIRST PASS run, save its actual run ID,
and follow the document through claims, assessments, submission, heartbeat,
publication, and finish. It does not launch SECOND or THIRD PASS or other agents.
The eligible first-pass backlog is included according to the live document.

## Completion and recovery

Python records the exact Codex session ID, logs, final response and review-owner
receipt under the configured state directory's `scrape-first-pass/` folder.
`run --resume` resumes that exact AI conversation and its own managed review run;
it never uses `--last` or guesses another task's run ID. A completed scrape is not
repeated. Resuming a completed workflow is a no-op. Plain `run` after completion
starts a new workflow. Separately launched scrapes are not implicitly adopted.

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

Only source files belong in GitHub. Logs, live prompts, results, state databases,
and credentials remain local. Install this folder inside the scraper project and
install `job-search-pipeline` in its root with executable permission.

```sh
python3 -m unittest discover -s scrape-first-pass -p 'test_*.py' -v
```

References: [Codex scripted execution and resume](https://learn.chatgpt.com/docs/non-interactive-mode),
[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

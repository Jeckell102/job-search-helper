# Job search helper: batching update, corrected installer (v2)

This update speeds up spreadsheet bookkeeping. It does not run AI or change the
fit-assessment policy. Job descriptions still require a separate review before
new opportunities are added.

## Install and resume Shield AI

1. Stop the current helper with **Ctrl+C**, and wait for the terminal prompt.
2. Save `update_job_search_batches_v2.py` in `~/Downloads`.
3. Run this complete command:

```bash
cd /home/chris/job-search-helper-FUrZBrxZ && .venv/bin/python ~/Downloads/update_job_search_batches_v2.py && ./job-search-helper resume --cycle CYC-16C2C6833C83 --apply --exclusive-writer
```

The updater tests the staged code first, backs up affected source files and an
existing SQLite state database, and installs into your existing project. It
refuses unknown source versions and refuses installation while a local writer
holds the same lock. It needs no extra packages. Your existing ATS diagnostics
and ampersand parser fix are retained. Configuration and OAuth tokens are not
changed. Installing the update does not write to Google Sheets.

The `resume` portion then continues the existing cycle with your current Google
write authorization. Already saved inventory is reused, so that inventory is
not downloaded again. If the local cache is missing, existing workbook recovery
can retrieve inventory again; recovery does not start a new cycle.

The original updater stopped because the installed `repository.py` contained
one different installation-help command: `.venv/bin/python3.11` instead of
`.venv/bin/python`. Comparing every uploaded source and test file established
that this was the only difference from the earlier patched release. This
corrected installer recognizes the reviewed uploaded version and preserves its
Python 3.11 help text. Unknown versions still stop before source replacement.

## What changes

- Cache operational workbook rows for job lookups instead of rereading them
  separately for every job. The prompt-reference tab remains excluded.
- Stage up to 25 inventory items or imported decisions per batch. Each actual
  write freshly resolves affected rows and preserves protected application
  statuses, dates, notes and formulas. It uses precise cell updates.
- Advance the local checkpoint in one transaction only after Sheets confirms
  the batch. If the response or checkpoint is lost, resuming reconciles the same
  identities and does not append duplicate jobs.
- Print saved progress after each batch, with processed inventory items,
  remaining pending reviews and elapsed time. The count is inventory processed,
  not opportunities accepted. Title exclusions may produce no history write.
- Recheck company pause/worker-claim flags between batches. The helper still
  supports one controlled writer; its local lock does not coordinate machines.
- Add conservative title exclusions for facilities/office coordinators and
  assistants, administrative/executive assistants, talent sourcers, selected
  warehouse/assembly trades, and internships. Existing coding, HR, accounting
  and other clear exclusions continue to apply. Generic Associate, Field,
  Coordinator, Operations, Product Marketing and technical leadership remain
  contextual, not automatic exclusions.
- Apply those rules to unreviewed jobs already queued in this cycle. Previously
  saved history stays in place with an exclusion reason; those jobs leave the
  pending assessment queue. Existing opportunities and completed assessments
  are not discarded by this cleanup. No AI assessment or reconsideration is
  fabricated. Frozen jobs remain frozen.

Example progress (illustrative):

```text
Shield AI: saved 75/448 inventory items processed; 60 pending reviews; 12s elapsed.
```

The actual inventory and review totals may differ. A batch can take several
seconds because read/write pacing and network latency still apply. In the
offline Google-service fixture, 448 eligible jobs used 18 history-write batches
and fewer than 150 total Google requests, including startup and completion.
That verifies fewer requests, not a measured completion time on your computer.

## Interruption and large batches

Use the same `resume --cycle ... --apply --exclusive-writer` command after an
interruption. The previous completed batch remains saved; the interrupted batch
may be replayed. Do not use `start` to recover this cycle.

An unusually large write payload stops before the write. Retry the same cycle
with a smaller batch if that specific message appears:

```bash
./job-search-helper resume --cycle CYC-16C2C6833C83 --apply --exclusive-writer --batch-size 5
```

Batch sizes 1–25 are supported. A local 1.8 MB guard leaves room below Google's
[recommended 2 MB request payload](https://developers.google.com/workspace/sheets/api/limits).
Do not sort, insert or delete spreadsheet rows while the writer is committing.

## After staging finishes

`Awaiting Review` is expected: the helper has prepared the assessment queue.
It has not spent AI tokens or judged fit. Export the current queue when ready:

```bash
./job-search-helper reviews --cycle CYC-16C2C6833C83 --output shield-ai-pending-reviews.jsonl
```

The export deliberately refuses to overwrite an existing file. Use a new name
if that filename already exists. Old exports can still contain title exclusions
removed by this update; use the new export for subsequent assessments.

## Verification

161 offline tests cover the underlying helper and the batching changes,
including failed writes, lost responses, failed local checkpoints, Ctrl+C during
planning, pauses between batches, formulas and user choices, title screening,
idempotent decision imports, payload limits, and a 448-job Google-service
fixture. The updater reruns the installed project's tests against staged code
before making changes. No live Google writes or workstation timing tests were
performed while preparing this update.

The corrected installer was also applied to a copy of the uploaded installation
with a simulated interrupted cycle. The check verified file/state preservation,
backups, refusal while a writer was running, refusal on unknown source changes,
idempotent reinstallation, and resumption without refetching saved inventory.

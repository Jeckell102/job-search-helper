# Interrupted-cycle recovery assessment

Observed 2026-11-18; read-only only. This note contains no production data.

## Current boundary

- No Job Search Helper scraper or coordinator process was running at the
  observation.
- `.state/scraper.lock` and `.state/writer.lock` contain `PID 485601`, which
  is absent. These files use advisory `flock`; an absent process cannot retain
  the lock. The files are retained as historical evidence and are not a safe
  reason to start another run.
- The local checkpoint's newest cycle is `CYC-B639C6D864EC`, an all-company
  cycle still marked `In Progress` with 764 queued Companies. Older cycles
  also remain unfinished.
- No pending Company-only request file was observed.

## Verified recovery rule

The normal Company-only request contract deliberately refuses to supersede an
unfinished cycle. Its visible recovery instruction is to retain any request,
retain locks, and use `./job-search-scraper start --resume` for the blocking
cycle. That command would resume the broad 764-company cycle; it is not a
safe one-company demonstration and must not be run as a shortcut.

## Safe next decision

Before a live Company-only pilot, use a dedicated recovery procedure that
preserves the existing broad cycle's checkpoint, inventories, workbook state,
and manual choices while explicitly resolving its ownership. It must create
fresh, reversible evidence and prove that a scoped request cannot lose or
silently supersede the broad work. No lock deletion, state rewrite, or broad
resume has been performed in this roadmap run.

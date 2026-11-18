# GDLS pilot independent live validation

Task: `WRAP-8be410e6f4`, COMP-0097 General Dynamics Land Systems.

Prepared only. No live request or inference was executed by this validation lane.
The validator passed an AST syntax check; runtime behavior remains untested until
the real company run. Do not execute while the worker is editing its checkout.

## Invocation after reviewed worker completion

Run inside the coordinator's reviewed read-only network-enabled validation
sandbox, exposing the development repo read-only and only a new isolated evidence
directory writable. Do not expose credentials, a browser profile, production
inventory databases, or production checkpoints. The script does not create this
OS isolation itself. The exact inner command is:

```sh
timeout --signal=TERM --kill-after=30s 1800s /home/chris/job-search-helper_old/.venv/bin/python -B /home/chris/.codex/.chatgpt-projects/g-p-6ab70f626df48191a04039506182677f/work/pilot-gdls-20261118/validate_live.py --repo /home/chris/job-search-helper_old/dev/wrapper-coder/tasks/WRAP-8be410e6f4/repo --output /home/chris/job-search-helper_old/temp/pilot-gdls-20261118/live-validation-1
```

Output must not already exist. Create/expose its parent before execution. A retry
must use a new numbered output directory, preserving failed evidence. A timeout
is a failed/incomplete live gate even if some jobs were downloaded.

The original configured inputs are `GD Land Systems`,
`https://www.gdls.com/careers/`, `COMP-0097`,
`General Dynamics Land Systems`. No adapter-specific call or injected fake is
used. Real default HTTP transport is observed without changing request behavior.
Each pass has a fresh local JSON detail checkpoint so the second pass does not
reuse the first pass's details. This writes no production checkpoint or database.

## Required final review

1. Confirm the AI diff is supported by source evidence. Before the AI's repair,
   saved historical context identifies a 308 from `/careers/job-search` to
   `/careers/search/`, possibly requiring a Next.js parser migration. Changing a
   URL alone is insufficient. Recheck the actual changed implementation.
2. Run company offline tests plus routing/transport policy regressions, including
   wrong business unit, pagination, duplicate/missing IDs, changed membership,
   description truncation, and default transport restrictions.
3. Run the live helper above. Inspect both output inventory files, saved public
   response bodies, redirect locations, request URLs and code hashes.
4. Prove the current search is explicitly restricted to **GD Land Systems**, not
   all General Dynamics businesses. Matching the company fields added by the
   adapter is not source evidence. Validate the public filter/facet and any
   per-record employer label. Parent-company boilerplate is insufficient.
5. Independently enumerate every advertised public listing page/cursor and its
   scoped posting IDs. Reconcile the complete set to each returned inventory;
   do not use a historical expected count. If embedded JSON lists a total, check
   unique scoped IDs against that total and verify the final page/termination.
6. For every returned ID, verify a corresponding public detail response contains
   the full role content, not merely a title, listing snippet, challenge, script,
   or site navigation. The helper's 120-character floor is only a gross integrity
   check and is not a semantic full-description test. Inspect the parser's
   extraction contract and any available source-provided description fields.
7. Verify both fresh reads have the same IDs and URLs and no missing detail/page,
   with an internal end-of-run reconciliation if provided by the adapter. A live
   membership change should cause a fresh bounded run, not a fabricated pass.
8. An empty inventory requires separately reviewed explicit empty-state evidence;
   this pilot helper fails empty results by default. Blocked, partial, timeout,
   source drift, or unresolved employer scope never passes.
9. Save a final reviewer receipt with result, code hashes, source evidence,
   pagination/count reconciliation, description coverage, stable reread, actual
   invocation, timing and limitations. Only then mark live validation passed.
   Installation, GitHub delivery, production run adoption, and Sheet publication
   are separate gates.

The helper's successful result is intentionally
`INTEGRITY_PASS_PENDING_PUBLIC_SOURCE_RECONCILIATION`. It does not automatically
certify the final operator gate or change coordinator state.

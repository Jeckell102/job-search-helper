# M4 bounded repair capability contract

Status: proposed implementation contract. This record authorizes no task,
release, scraper run, or Jetson request by itself.

## Purpose

An M3 qualified repair is evidence that a known failure category occurred; it
is not authority to write a wrapper or to start coordinator work. M4 will
allow only a narrowly defined, versioned capability profile to convert that
held evidence into one paused coordinator task. Everything else remains held
for engineering review.

## Required matching inputs

The profile must exactly match all of the following trusted values:

- Company ID and current integration-relevant Company revision;
- provider and installed adapter/executor version from the immutable outcome;
- a declared failure category that the profile supports;
- an approved source-host and URL scope from the current Company record; and
- an immutable profile version, source/test file allowlist, and regression
  test list.

The current acceptance matrix freezes Forterra/Rippling, Allen
Control/Greenhouse, and General Atomics/BrassRing as test cases. It does not
qualify any profile yet. PDW remains a shared-Rippling regression case and
goTenna remains an engineering-hold control.

## Safe state changes

1. M3 records the immutable outcome and creates at most one held repair key.
2. M4 evaluates profiles without side effects. No exact match leaves the key
   held with a plain-language engineering-review reason.
3. An exact profile can create one paused, Company-version-bound task with
   fixed files, tests, budgets, and evidence requirements.
4. A fresh current-Company check is required before every resume, queue claim,
   direct work step, model request, validation, or release action.
5. A model proposal can change neither the profile, file scope, test list,
   identity, budget, nor release state. Unknown or no-progress results end at
   a durable hold.

## Minimum implementation checks

- Same held repair/profile replay returns the same paused task.
- A mismatched Company, provider, adapter version, failure category, source
  revision, or host creates no task and changes no control.
- A stale/missing current Company revision pauses a previously promoted task
  before any worker receipt.
- An unsupported capability produces an engineering hold, never a generic
  code-generation task.
- Profile selection is deterministic and has no Jetson/network side effect.

## Remaining gate

Implement the profile registry and deterministic selector in the isolated
feature copy, then obtain independent QA before a bounded real-company
preflight. No profile is enabled for automatic promotion or release yet.

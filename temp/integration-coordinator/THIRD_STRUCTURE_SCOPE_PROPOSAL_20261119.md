# Third distinct-structure scope proposal — 2026-11-19

## Status

**Independent QA accepts this as an owner-reviewed scope-amendment proposal
only. It is not approved, not added to the frozen acceptance matrix, and not
authorized for a scrape, repair, release, Google access, or data write.**

The roadmap’s Milestone 6 exit gate requires at least three unfinished
companies with distinct source structures, a shared-adapter regression, and a
separate correctly held external-block case. The frozen matrix presently has
completion candidates for Rippling and Greenhouse, a BrassRing hold, and a
shared-Rippling regression. A correct BrassRing hold does not make that Company
complete. Therefore, a third successful distinct structure needs an explicit
scope amendment and independent QA; it cannot be silently substituted.

## Proposed candidate

| Field | Read-only evidence |
|---|---|
| Company | `COMP-0024` Draper |
| Distinct source structure | Workday public CXS board |
| Current protected Company state | Active, `Partial`, linked to the historical broad cycle; no current-cycle inventory record exists for this Company |
| Historical incomplete evidence | A recorded Workday detail request encountered human verification; browser fallback saved no descriptions and completeness remained unknown |
| Historical counter-evidence | An older saved cycle recorded a complete 222-posting Workday inventory; that result is historical only and does not establish current eligibility |
| Existing bounded implementation | `workday.py` and its existing focused Workday tests |

## Required approval and preflight before amendment

1. Independent QA has accepted this as a candidate *for a scope amendment*, not
   as a completed or currently qualified case. Its review confirms the Workday
   structure is distinct from the frozen Rippling, Greenhouse, and BrassRing
   cases, but rejects every inference of current eligibility from historical
   data.
2. The owner must approve the scope amendment. The coordinator must then record
   a revision to the acceptance matrix naming this
   Company, its exact current official source, allowed scope, expected failure
   classification, bounded repair capability, expected AI contribution, and
   hard engineering-hold conditions.
3. Fresh public evidence must establish the current employer scope, listing and
   detail accessibility, pagination/completeness conditions, source revision,
   and whether human verification remains. Any access block remains a hold and
   earns no completion credit.
4. Owner approval is required before a matrix amendment or any live Company
   action. The pending Sheets-conflict/publisher gate remains independent and
   must not be bypassed.
5. The scoped run, if later authorized, must prove only this Company’s request,
   durable storage, confirmed synchronization, restart/duplicate behavior, and
   independent QA evidence. It must not expand the historical backlog.

## Explicit non-results

- No candidate has been substituted into the frozen matrix.
- No public request, browser session, inference request, repair task, or
  release was started.
- No current Workday completeness, source accessibility, or eligibility has
  been inferred from historical records.
- No automatic profile, release, or repair is available: the current profile
  registry remains deliberately empty. Any remedy would require a separately
  qualified, revision/provider/adapter-bound profile and F5 evidence.

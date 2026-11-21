# Draper current public source availability — bounded check

2026-11-21, 04:17:54 Eastern. **HELD_EXTERNAL_PUBLIC_AVAILABILITY.** Both authorized requests ran: one official careers read and one exact provider observation. Network work stopped after that observation; no retry, alternate hostname/API, login, CAPTCHA, browser bypass or bulk scan was attempted.

## Current evidence

The current official [Draper careers page](https://www.draper.com/careers) exposes Current Openings and View Our Job Openings links to the exact [Draper_Careers Workday board](https://draper.wd5.myworkdayjobs.com/en-US/Draper_Careers). Following that one official link produced a redirect to `https://wd5.myworkday.com/wday/drs/outage?t=draper&s=Draper_Careers`. The public reader reported a non-retryable fetch/access error, with a 500 diagnostic, because the outage target was inaccessible to that reader.

This independently reconfirms the employer-to-tenant link and repeats the earlier recorded outage-path result. It does not prove a universal Workday outage, establish the origin HTTP status independently of the reader's diagnostic, or show that other legitimate clients could not access the board. No usable listing, job identity set, complete descriptions or inventory total was obtained. The external limitation is that this authorized public observation cannot reach an ordinary usable exact-tenant listing.

## Matrix disposition

Read first: `S6_DRAPER_SOURCE_PREFLIGHT_20261121.md`, `FINAL_ACCEPTANCE_READINESS_20261119.md`, current Sprint 6 section of `sprint_roadmap.md`, and the current coordinator checkpoint. The original frozen matrix names Forterra/Rippling and Allen/stale Greenhouse as completion candidates, PDW as regression control and General Atomics as external hold. The newer Sprint 6 overlay explicitly treats Allen's independently qualified Ashby migration as its candidate structure. Draper remains a proposed distinct Workday completion structure; the earlier scope proposal and current official linkage are not completed-source qualification or a matrix amendment. No case was substituted and no completion credit was earned.

## Eventual bounded readiness test

For a later separately scheduled/approved use, first require one normal public observation of this same employer-linked board to return a usable listing without redirect to outage/login/CAPTCHA or widening employer scope. If it remains unavailable, retain the external hold and proceed with unrelated qualified work; do not automatically retry in a loop.

Only after availability returns, an explicitly bounded normal-adapter qualification must verify the exact tenant/site, all listing pages, unique stable IDs, full descriptions for every included job, and a final identity/content reread. Missing pages, changed total/IDs, incomplete descriptions or foreign-employer postings fail that qualification. Freeze the current Company/source revision and document the explicit case-matrix amendment before it can count as the third completion candidate. The release owner separately owns supported-capability qualification, actual admission, protected historical-cycle isolation, release/runtime pins and exact storage/publication evidence. This read-only availability check supplies none of those authorities.

Evidence lives here in `OBSERVATION.json`. No production files, Jobs, State, Inbox, workbook, services, queues, Google or Jetson were accessed or changed. Report and observation are sanitized; no job payloads or credentials were collected.

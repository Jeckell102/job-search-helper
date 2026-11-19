# COMP-0164 Allen Control Systems public preflight

Performed: 2026-11-19 (UTC). Scope was public unauthenticated HTTP/HTML
inspection only: no project source, scraper, local state, Sheets/Google,
queue, lock, service, login, or form interaction.

## Result

**Qualified only for a narrow, reviewed configuration proposal; not released.**

The historical Greenhouse tenant is stale (public HTTP 404). Current
first-party evidence instead establishes an employer-scoped Ashby board.
This permits source/independent-QA review of an exact configuration only; it
does not permit a release, scrape, write, automatic migration, or broad work.

## Evidence

| Check | Result |
| --- | --- |
| Official employer page | `https://www.allencontrolsystems.com/company` exposes its Join Our Team area. |
| Employer-to-tenant link | Its rendered page contained 19 `gw-jobs-apply` links, each under `https://jobs.ashbyhq.com/allen-control-systems/<UUID>`, and embeds `https://api.ashbyhq.com/posting-api/job-board/allen-control-systems`. |
| Board identity | `https://jobs.ashbyhq.com/allen-control-systems` rendered as Allen Control Systems Jobs, linked back to the official domain, and showed Open Positions (19). |
| Current coverage | The board showed 19 distinct detail links, matching 19 distinct official-page detail links; no pagination or Load More control was rendered. This is a current snapshot, not a fixed future count. |
| Detail evidence | The public Electronics Technician detail `c87682d7-0ba5-4734-962b-e45d2b41b1b7` rendered complete role content, Austin location, full-time status, department, and ACS employer overview. |

Direct browser navigation to the public Ashby API was blocked by client policy,
but the official page explicitly embeds it and every official current apply link
uses the same tenant. The provider transition must be treated as a new exact
Ashby configuration, not a Greenhouse redirect repair.

## Next boundary

Any proposal must pin only the official page, `jobs.ashbyhq.com/allen-control-systems/`
path prefix, and public Ashby board identity. Require source-level and
independent QA before installation, then a later guarded company-only normal
pilot with fresh list/detail reread, stable identities, durable local receipt,
and separately verified normal synchronization. Keep automatic release and
broad backlog processing disabled.

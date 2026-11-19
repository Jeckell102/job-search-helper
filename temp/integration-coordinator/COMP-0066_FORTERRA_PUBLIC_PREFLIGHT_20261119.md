# Forterra `COMP-0066` public preflight

Performed: 2026-11-19 (America/New_York)
Scope: public unauthenticated HTTP/HTML only. No scraper, project source,
database, Sheets, queue, lock, service, login, or Google action was used.

## Result

**Qualified for a guarded company-only candidate; not released.**

The official Forterra careers page embeds Rippling board ID `forterra`. The
board is publicly reachable, exposes stable UUID detail paths, and has a
finite observed pagination boundary. This supports isolated parser/fixture
implementation and coverage testing only; it does not authorize a scraper
release, production run, automatic release, or broad-backlog admission.

## Evidence

| Check | Evidence |
| --- | --- |
| Official employer source | `https://www.forterra.com/careers` returned HTTP 200 and declares `boardId = 'forterra'`, building the Rippling jobs URL. |
| Exact tenant | `https://ats.rippling.com/forterra/jobs?page=0` returned HTTP 200; this is distinct from the goTenna tenant. |
| Public details | UUID-keyed details for `90716026-f864-4de5-b198-949f76c02aa3` and `0c1ee1f5-3574-47dc-b06d-57862dbc2c55` returned HTTP 200. |
| Pagination | Live detail counts were page 0: 20, page 1: 20, page 2: 20, page 3: 2, page 4: 0. |

The empty terminal page is HTTP 200, so a future parser must stop on an empty
result page or equivalent advertised pagination state, not a 404. The live
snapshot contained 62 unique detail paths across pages 0--3. Counts and title
sets are not frozen release expectations because public caches showed source
drift; only the tenant and pagination contract are retained.

## Next boundary

Before any company-only live run, repeat this preflight and require normal
release, queue, receipt, storage, and independent-QA gates. Keep broad
processing and automatic release disabled.

URLs checked:

- https://www.forterra.com/careers
- https://ats.rippling.com/forterra/jobs?page=0
- https://ats.rippling.com/forterra/jobs?page=1
- https://ats.rippling.com/forterra/jobs?page=2
- https://ats.rippling.com/forterra/jobs?page=3
- https://ats.rippling.com/forterra/jobs?page=4

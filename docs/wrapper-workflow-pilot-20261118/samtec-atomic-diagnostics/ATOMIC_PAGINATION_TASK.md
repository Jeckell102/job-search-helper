# Next bounded AI task: Samtec listing traversal

Status: specification only. No wrapper implementation or inference performed by this lane. Start only after the separate route proposal passes independent scope tests. Keep the failed coordinator attempts and all diagnostic costs recorded; this is an assisted atomic repair, not autonomous completion.

## Verified public evidence

- `listing-inspection.html`: `/samtec/jobs` is a featured landing page with four unique job links, a Featured Jobs heading, and no `jv-job-list` class.
- `search-inspection.html`: `/samtec/search` contains 50 unique job links on the first page and the `jv-job-list` class. Fifty is a page count, not total inventory.
- Lines 952–959 of the saved search HTML expose the actual continuation anchor: class `jv-pagination-next`, href `//jobs.jobvite.com/samtec/search/?p=1`, visible text `Next`. Neither `rel=next` nor an aria-label is required by this observed template.
- The later bounded structure observation independently confirms that class and continuation URL. A subsequent bounded read-only traversal now verifies three listing pages and their termination as detailed below. This remains public listing evidence, not scraper/detail validation.

## Exact context for the model

Supply the current isolated workspace SHA and exact excerpts from `src/job_search_helper/shared_boards.py`; regenerate line ranges if the accepted route patch shifts them:

1. `board_link`, current lines 123–143: accepted Samtec routing plus existing URL/filter validation.
2. `allowed`, lines 190–220: global HTTPS/credentials/port/fragment/control-character checks, same-host boundary, and Jobvite endpoint restriction.
3. `Transport.request`, lines 286–337: requests pass through `allowed`; redirects are disabled, and status/response/retry bounds remain enforced. The guard is the module-level `allowed` function, not a method named `_allowed`.
4. `Links`, lines 542–558, and `html_listing`, lines 569–586: real class extraction, scoped job-link parsing, current next-page detection, explicit empty-state requirement.
5. `listing` dispatch near line 437 and `_fetch` reconciliation near lines 693–766: each inventory reread must traverse all pages. Existing full-detail and reconciliation logic must remain intact.

Do not supply the whole registry or unrelated provider implementations. One atomic task may first propose the tightly scoped transport allowance; a following task may propose listing traversal. Every proposal needs an exact unique old excerpt and current SHA, followed by independent testing before application.

## Required behavior

Support the observed Samtec search listing and its continuation pages only. Normalize relative/protocol-relative links against the current page; follow only validated HTTPS URLs on `jobs.jobvite.com` under the exact `samtec` search path. Permit only the observed numeric `p` pagination parameter on this narrowly scoped route; reject duplicate keys, extra filters, malformed values, unrelated paths, credentials, alternate ports, fragments, and other employers. Preserve query-free job-detail handling and all other provider/Jobvite behavior.

Traverse every observed next link with a finite page budget and visited-page detection. Validate each page's listing structure and responses. Retain stable unique job identifiers, full titles, and same-employer detail URLs. Duplicate identical rows across boundaries may reconcile; conflicting rows for the same ID must not silently overwrite one another. An invalid next link, loop, page-budget exhaustion, missing container, challenge, failed later page, or malformed data must remain partial/blocked, never complete.

Preserve explicit empty-state validation. A failed, malformed, generic, or merely empty page is not evidence of zero openings. A nonempty first page plus a failed or ambiguous continuation is incomplete.

## Independent acceptance tests before live validation

- Existing route/provider suite still passes. Samtec root listing and observed pagination work; other employers retain original behavior.
- Adversarial URL matrix rejects cross-host/cross-company links, HTTP, credentials, alternate ports, fragments, encoded path tricks, duplicate `p`, nonnumeric/negative parameters, and extra filters before network requests.
- Two- and three-page fixtures with class-based Next anchors return the union of all scoped IDs. Boundary duplicates cannot hide conflicting data.
- Malicious/out-of-scope Next links, repeated pages, cycles, page-limit exhaustion, missing container, explicit challenge, non-2xx later response, and incomplete empty continuation fail closed.
- Detail endpoints remain guarded. Full descriptions are fetched and validated for every retained role; one failed detail prevents complete status.
- `_fetch` performs a second full traversal, not a first-page-only reread. A job added, removed, or changed only on a later page triggers existing reconciliation; persistent change remains incomplete.
- Explicit zero inventory is accepted only with valid scoped structure and an explicit empty-state observation, followed by the required stable reread.

## Live acceptance

Run normal `fetch_inventory` dispatch with default production transport against the isolated candidate. Independently enumerate all public search pages and compare stable IDs/URLs and counts; do not use four featured roles or the 50-row first page as the expected total. Verify full descriptions for all retained roles and the complete second inventory traversal. Keep production scheduling paused and install nothing until that evidence passes review. If public access fails, record the precise blocker rather than relaxing guards.

## Fresh three-page public traversal

Saved on MuleLab at `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/public-pagination-evidence-1/receipt.json`, with the exact HTML and SHA256 for each response:

| Request | Observed range label | Unique jobs | Continuation |
|---|---|---:|---|
| `/samtec/search` | `1-50 of 148` | 50 | class `jv-pagination-next`, `/samtec/search/?p=1` |
| `/samtec/search/?p=1` | `51-100 of 148` | 50 | class `jv-pagination-next`, `/samtec/search/?p=2` |
| `/samtec/search/?p=2` | `101-148 of 148` | 48 | no next anchor; previous anchor remains |

All three returned HTTP 200 with complete bounded HTML and the required listing class. Their union contains **148 unique job IDs**, agreeing with each page's declared total. This count is a dated observation and must be refreshed during live validation; do not hardcode it.

The final page still has a `jv-pagination` container and `jv-pagination-prev`; absence of the whole pagination container is not the termination condition. Do not treat Previous as Next. A prior-page link to `?p=0` exists on page 1; this collector did not follow it. Current observed forward traversal uses only `p=1` and `p=2`.

Add independent checks for contiguous displayed ranges, consistent declared totals, and final unique-count reconciliation. A missing Next on a page advertising an unfinished range must remain incomplete. All-page stable reread and full descriptions are still unverified and required.

# Crown Equipment priority-list preflight

On November 22 at 18:05 Eastern the coordinator took Crown Equipment
(COMP-0588, W06/READY) from the existing partial-integration audit. This
was proactive screening of one company, without relying on a new Company
event or an existing repair assignment.

The installed source mapping selects Crown's official US SuccessFactors
board at https://us-careers.crown.com/search/?createNewAlert=false&q=&locationsearch=.
The installed transport returned HTTP 200 for that exact listing.
The installed first-page parser raised a partial result because the listing
did not expose one consistent published result range. Its HTML parser saw
300 posting anchors. A single detail at the same host, posting 1395445000,
returned HTTP 200 with 3,043 description characters.

This reproduces a current, employer-scoped failure in the listing
completeness check. The two reads do not establish that 300 is the full
inventory. Next, determine whether Crown publishes a reliable total or
end-of-inventory signal. If it does, preserve one small regression fixture
and use the established company-scoped admission with the reviewed Sprint
6 case scope. Keep the current completeness guard until that evidence
exists. Feed the installed queue through a real company-only partial
outcome. Keep Embraer held.

No scrape request, queue write, inference, release or workbook action was
performed. No Sprint 6 credit was earned.

A follow-up read found 100 distinct numeric IDs behind the 300 repeated
anchors, with no visible result range or next-page link. The same official
host's sitemap returned 530 unique canonical job IDs. All 99 strict
same-host HTTPS IDs in the search response were present. The remaining
listing link form and five noncanonical sitemap entries need to be
classified before claiming coverage. Crown is a promising repair candidate
using the existing SuccessFactors sitemap approach, with exact Crown-only
scope. The sitemap count is evidence of a larger published set, not proof
of complete inventory or of valid full descriptions for all postings.

## Source-only admission checkpoint

The 535 distinct sitemap URLs are all on the same exact Crown host.
They consist of 530 standard job URLs and five job URLs under the
`/TheGoods/job/` and `/17West/job/` sections. The alternate visible job is
one of the sitemap's five. One separately sampled detail from each section
returned HTTP 200, an exact canonical URL, one title, and one full
description. The listing yielded 100 distinct jobs and no pagination
markers. This supports an exact Crown-only candidate. The fixture
describes the proposed sitemap behavior and still requires independent
live proof of full inventory and stable membership before publication.

Independent review confirmed the installed queue cannot accept Crown:
operator partial supports only Amphenol and Embraer. The ordinary Company
event route requires actual event provenance and its repair path is not
generic. The current SuccessFactors partial has no typed failure.
Use a real company-only operator request and reuse the existing guarded
partial settlement. Then bind that exact settlement and runtime to a
single coordinator task. No invented Company event. Crown remains outside
the frozen Sprint 6 completion matrix pending independent review.

The source-only two-file patch captures a distinct typed Crown failure
when the exact board and Company identity match, the first page lacks a
published range, and its job URLs have valid first-party identities.
An isolated normal dispatcher read returned a typed partial immediately
from the official board (100 IDs; listing digest
`6709919bce6d11cf80569e179b6015059dca3980a8e9f21ff54b4b5ad0eb965d`).
It did not save jobs or start an inference. Three focused witness checks
and 29 existing Crown and SuccessFactors checks passed. Two proposed
repair regressions fail on the production baseline as expected. The
patch deliberately leaves the actual repair for the Jetson.

Staged patch and fixtures are in `/tmp/jsh-crown-repair-evidence/`.
Production source, queue and workbook are unchanged. Next wire and
independently review one exact operator settlement and coordinator
handoff using this typed failure, then check the required current
production Company facts and scoped request before opening a release.

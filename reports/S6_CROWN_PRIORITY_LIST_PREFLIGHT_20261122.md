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

# COMP-0072 — General Atomics Aeronautical Systems (GA-ASI)

## Read-only public preflight — 2026-11-19

Scope: public HTTP/HTML only. No project code, database, Sheets, queue,
scraper, login, or service/lock interaction occurred.

## Confirmed evidence

1. **Entity and official careers handoff.** GA-ASI's own contact page identifies
   “General Atomics Aeronautical Systems, Inc. (GA-ASI)” at Poway, California,
   and directs applicants to `https://www.ga-careers.com/`. That URL redirects
   to the General Atomics official careers page.
   - https://www.ga-asi.com/contact
   - https://www.ga-careers.com/ (redirects to https://www.ga.com/careers/)
2. **Official BrassRing relationship.** The official General Atomics careers
   page labels its U.S.-jobs link “Search all US Jobs” and links it to
   BrassRing. The linked public board uses `partnerid=25539&siteid=5313`; its
   Talent Community page says the career page is powered by BrassRing.
   - https://www.ga.com/careers/
   - https://sjobs.brassring.com/TGnewUI/Search/Home/Home?partnerid=25539&siteid=5313
   - https://community.brassring.com/GeneralAtomicsandAffiliatedCompanies/TalentCommunity
3. **GA-ASI membership/details.** A public job-detail page on that partner/site
   labels the employer “General Atomics Aeronautical Systems” and names
   “General Atomics Aeronautical Systems, Inc. (GA-ASI)”: `jobid=5237249`,
   requisition `58113BR`, Poway, California.
   - https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?PageType=JobDetails&jobid=5237249&partnerid=25539&siteid=5313
4. **Pagination exists only at board scope.** The public board reports a large
   combined result set and paginated result pages (one view showed page 1 of 7
   for 314 results; the unfiltered entry point advertised 924+ opportunities).
   That proves pagination for the shared General Atomics and affiliated-company
   board, not GA-ASI alone.

## Hold conclusion

**Remain frozen; do not admit this provider to a company-only pilot.** The
evidence establishes the official GA-ASI-to-General-Atomics BrassRing
relationship and proves GA-ASI jobs occur on partner 25539/site 5313. It does
not establish an official stable GA-ASI-specific search URL, facet/API filter,
or pagination boundary. The board is shared with affiliated companies; using
parent-board totals or inferring a company filter would widen scope and violate
the company-only gate.

Required next evidence before admission: an official GA-ASI-specific search
entry point or reproducibly documented public filter whose jobs and page count
are confined to GA-ASI, followed by controlled parsing/identity review.

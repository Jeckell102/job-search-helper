# Festo source mapping qualification

**Status:** isolated provider qualification passed. Production remains on
its prior release and there is no publication from this candidate.

Festo COMP-0560 had a category directory configured as the job listing.
The employer's search form leads to its own unfiltered search. The local
authority review found one matching Company, no country or subsidiary
restriction, and no distinct FluidX or Didactic record. The official
FluidX-prefixed listing named Festo India Private Ltd. as its employer.
See the [official search](https://jobs.festo.com/search/),
[official posting](https://jobs.festo.com/job/Bangalore%2C-Karnataka-FluidX-Fullstack-Developer/1276955301/),
and [Festo site certificate](https://www.festo.com/media/cms/media/editorial/downloads/festo_at_downloadfiles/Zertifikat_14001_en_2022.pdf).

The existing source registry remaps the confirmed category and bare
search URLs to the ordered results URL. The existing SuccessFactors
adapter keeps that ordering during pagination and rereads every page.
A deliberately filtered replacement link stays intact. The current
Company's stored URL stays intact through candidate validation.

A single paced provider qualification used normal `fetch_inventory`
dispatch starting from the real configured source. Initial pagination
and final reread matched on all six pages. All 126 distinct postings
had full description bodies with matching canonical URLs. The run made
12 listing and 126 detail reads, all HTTP 200, and stored only summary
evidence. The structured employer metadata probe found no names in its
checked format. Employer scope is supported by the separate official
board, Company mapping, and identified branded-posting evidence. Zero
production writes or Jetson calls.

Independent QA rejected the initial candidate's ownership check.
The repaired candidate requires exact Company ID and normalized Festo
name before provider access. The three focused tests pass, including
both foreign-owner paths with zero requests. The valid Company
continues through the same measured provider code. The isolated patch
applies cleanly against the current installed source.

This is a deterministic source correction. It can support a later
eligible Company progressing while the earlier hold stays intact, once
the exact guarded release, company-only run, and local/workbook/receipt
joins are verified. The frozen Sprint 6 repair sequence remains 0/3.
The genuine new-Company first-Start and live lost-ack gates remain open.

[Pagination receipt](/tmp/jsh-s6-festo-preflight/PAGINATION_OBSERVATION.json) ·
[Complete provider receipt](/tmp/jsh-s6-festo-preflight/CANDIDATE_OBSERVATION.json) ·
[Reviewed patch](/tmp/jsh-s6-festo-preflight/FESTO_SOURCE_MAPPING_20261122.patch) ·
[Initial QA rejection](S6_FESTO_SOURCE_OWNER_QA_REJECT_20261122.md)

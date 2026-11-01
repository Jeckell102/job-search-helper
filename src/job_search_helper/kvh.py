"""KVH Industries' two official public iCIMS boards."""
from .ats import FetchError, Inventory
from .icims import fetch_icims

US = "https://careers-kvh.icims.com/jobs/search?in_iframe=1"
INTERNATIONAL = "https://internationalcareers-kvh.icims.com/jobs/search?in_iframe=1"

def fetch_kvh(url, company_id, company, transport):
    jobs = []
    sources = []
    failures = []
    seen = set()
    for source in (US, INTERNATIONAL):
        board = source.split("/jobs", 1)[1]
        try:
            result = fetch_icims("/jobs" + board, source.split("/jobs", 1)[0], company_id, company, transport)
            jobs.extend(result.jobs)
            sources.append(result.source_url)
            if result.status != "complete":
                failures.append(result.reason)
        except Exception as exc:
            failures.append(f"{source}: {exc}")
    unique = []
    for job in jobs:
        # iCIMS emits a company-level job key that is not board-specific;
        # use the stable posting ID first so US and international feeds can
        # be merged without collapsing distinct postings.
        ident = job.get("posting_id") or job.get("official_url") or job.get("job_key")
        if ident in seen:
            failures.append("duplicate posting across KVH boards")
            continue
        seen.add(ident); unique.append(job)
    if failures:
        return Inventory("partial", unique, "KVH composite: " + "; ".join(failures), ",".join(sources))
    return Inventory("complete", unique, f"KVH composite: retrieved {len(unique)} postings across both official iCIMS boards.", ",".join(sources))

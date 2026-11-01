from job_search_helper.company_sources import REPAIRS, repair_source


CASES = {
    "COMP-0023": ("ENSCO", "Greenhouse", "https://job-boards.greenhouse.io/ensco"),
    "COMP-0026": ("Research Innovations, Inc. (RII)", "Lever", "https://jobs.lever.co/researchinnovations.com"),
    "COMP-0027": ("Two Six Technologies", "Greenhouse", "https://twosixtech.com/careers/current-opportunities/"),
    "COMP-0028": ("STR", "Greenhouse", "https://job-boards.greenhouse.io/systemstechnologyresearch/jobs/4701225006"),
    "COMP-0051": ("Anduril Industries", "Greenhouse", "https://boards.greenhouse.io/andurilindustries"),
    "COMP-0052": ("Shield AI", "Lever", "https://jobs.lever.co/shieldai"),
    "COMP-0053": ("Palantir Technologies", "Lever", "https://jobs.lever.co/palantir"),
    "COMP-0054": ("Saronic Technologies", "Ashby", "https://jobs.ashbyhq.com/saronic"),
}


def test_broader_company_routes_are_exact_and_employer_scoped():
    for cid, (company, ats, source) in CASES.items():
        assert cid in REPAIRS
        fixed_ats, fixed_url, note = repair_source(ats, source, cid, company)
        assert fixed_ats == REPAIRS[cid]["ats"]
        assert fixed_url == REPAIRS[cid]["url"]
        assert note.startswith("Verified company source repair:")
        assert repair_source(ats, source, cid, "Unrelated Employer") == (ats, source, "")

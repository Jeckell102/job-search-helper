"""Annapolis' published role inventory, using captured WordPress page structure."""
from __future__ import annotations

from collections import Counter
from html import unescape
from pathlib import Path
import re
from unittest.mock import patch

import pytest

from job_search_helper import annapolis_micro as adapter
from job_search_helper.ats import FetchError, HTTPResponse, fetch_inventory


FIXTURES = Path(__file__).parent / "fixtures" / "annapolis_micro"
SOURCE = "https://www.annapmicro.com/careers-at-annapolis-micro-systems/"
CATEGORY = SOURCE + "engineering-careers/"
SOFTWARE = CATEGORY + "senior-software-engineer/"
HARDWARE = CATEGORY + "senior-hardware-engineer/"
COMPANY_ID = "COMP-0427"
COMPANY = "Annapolis Micro Systems"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def reply(body, status=200, headers=None):
    return HTTPResponse(status, body.encode(), headers or {})


def role(url, title):
    """Change identity on a full captured job article for synthetic sibling jobs."""
    return fixture("senior-software.html").replace(SOFTWARE, url).replace(
        "Senior Software Engineer", title
    )


class Pages:
    """URL-addressed fake; list values advance on reread, then keep the last value."""

    def __init__(self, overrides=None):
        self.pages = {
            SOURCE: fixture("careers.html"),
            CATEGORY: fixture("engineering.html"),
            SOFTWARE: fixture("senior-software.html"),
            HARDWARE: role(HARDWARE, "Senior Hardware Engineer"),
        }
        self.pages.update(overrides or {})
        self.urls = []
        self.counts = Counter()

    def get(self, url):
        self.urls.append(url)
        occurrence = self.counts[url]
        self.counts[url] += 1
        value = self.pages.get(url, reply("Not found", 404))
        if isinstance(value, list):
            value = value[min(occurrence, len(value) - 1)]
        if isinstance(value, Exception):
            raise value
        return reply(value) if isinstance(value, str) else value


def run(pages=None, **kwargs):
    return adapter.fetch_annapolis_micro(
        kwargs.pop("url", SOURCE),
        kwargs.pop("company_id", COMPANY_ID),
        kwargs.pop("company", COMPANY),
        pages or Pages(),
        **kwargs,
    )


def assert_two_full_roles(result):
    assert result.status == "complete", result.reason
    assert {job["title"] for job in result.jobs} == {
        "Senior Software Engineer", "Senior Hardware Engineer"
    }
    assert {job["url"] for job in result.jobs} == {SOFTWARE, HARDWARE}
    assert len({job["posting_id"] for job in result.jobs}) == 2
    for job in result.jobs:
        assert job["company_id"] == COMPANY_ID
        assert job["company"] == COMPANY
        assert not job["req_id"]  # URL identity must not masquerade as a requisition.
        assert job["location"] == "Annapolis, MD (On-site)"
        # Compare every word of the captured article, including nested lists
        # and its final pay clause, rather than trusting a length threshold.
        article = fixture("senior-software.html").split('<div class="entry-content">', 1)[1].split(
            '</div><footer class="entry-footer">', 1
        )[0]
        expected = unescape(re.sub(r"<[^>]+>", " ", article)).replace(
            "Senior Software Engineer", job["title"]
        )
        assert " ".join(job["description"].split()) == " ".join(expected.split())
        assert "B.S. in Computer Engineering" in job["description"]
        assert "High-Performance DMA" in job["description"]
        assert "$135,000/yr to $230,000/yr" in job["description"]
        assert "Human Resources" not in job["description"]
        assert "Complete our online application" not in job["description"]
        assert "Company navigation" not in job["description"]
        assert "Copyright" not in job["description"]


def test_normal_configured_fetch_uses_injected_transport_and_category_inventory():
    pages = Pages()
    result = fetch_inventory(
        "Annapolis Micro careers", SOURCE, COMPANY_ID, COMPANY,
        discovery_transport=pages,
    )
    assert_two_full_roles(result)
    # The root advertises only the software job; hardware is category-only.
    assert pages.counts[CATEGORY] >= 2
    assert pages.counts[SOURCE] >= 2
    assert not any("apply-now" in url for url in pages.urls)


def test_normal_fetch_preserves_explicit_primary_transport():
    pages = Pages()
    result = fetch_inventory("Annapolis Micro careers", SOURCE, COMPANY_ID, COMPANY, pages)
    assert_two_full_roles(result)
    assert pages.urls


def test_normal_fetch_rejects_an_unrecognized_source_for_the_company():
    pages = Pages()
    result = fetch_inventory(
        "Annapolis Micro careers", "https://other.example/careers/", COMPANY_ID, COMPANY, pages
    )
    assert result.status == "unsupported", result.reason
    assert not pages.urls


def test_direct_fetch_accepts_current_inventory_without_hardcoded_count():
    third = CATEGORY + "firmware-engineer/"
    category = fixture("engineering.html").replace(
        "</ul>", f'<li><a href="{third}">Firmware Engineer</a></li></ul>', 1
    )
    result = run(Pages({CATEGORY: category, third: role(third, "Firmware Engineer")}))
    assert result.status == "complete", result.reason
    assert {job["url"] for job in result.jobs} == {SOFTWARE, HARDWARE, third}


def test_role_content_excludes_application_form_hidden_text_and_sidebar():
    body = fixture("senior-software.html").replace(
        '<h4>Annapolis, MD (On-site)</h4>',
        '<h4>Annapolis, MD (On-site)</h4>'
        '<form><h1>Application</h1><p>FORM PRIVATE FIELDS</p></form>'
        '<script>SCRIPT GARBAGE</script><style>STYLE GARBAGE</style>'
        '<div hidden>HIDDEN GARBAGE</div>',
    )
    result = run(Pages({SOFTWARE: body}))
    assert_two_full_roles(result)
    software = next(job for job in result.jobs if job["url"] == SOFTWARE)
    assert software["title"] == "Senior Software Engineer"
    for excluded in ("FORM PRIVATE FIELDS", "SCRIPT GARBAGE", "STYLE GARBAGE", "HIDDEN GARBAGE"):
        assert excluded not in software["description"]


def test_listing_order_changes_do_not_make_stable_membership_partial():
    first = fixture("engineering.html")
    swapped = first.replace(SOFTWARE, "__first__").replace(HARDWARE, SOFTWARE).replace(
        "__first__", HARDWARE
    ).replace("Senior Software Engineer", "__title__").replace(
        "Senior Hardware Engineer", "Senior Software Engineer"
    ).replace("__title__", "Senior Hardware Engineer")
    assert_two_full_roles(run(Pages({CATEGORY: [first, swapped]})))


def test_category_membership_change_on_final_reread_is_partial_with_downloads_retained():
    first = fixture("engineering.html")
    third = CATEGORY + "firmware-engineer/"
    changed = first.replace(HARDWARE, third).replace("Senior Hardware Engineer", "Firmware Engineer")
    result = run(Pages({CATEGORY: [first, changed], third: role(third, "Firmware Engineer")}))
    assert result.status == "partial", result.reason
    assert {SOFTWARE, HARDWARE}.issubset({job["url"] for job in result.jobs})


def test_removed_membership_on_final_reread_is_partial():
    first = fixture("engineering.html")
    changed = first.replace(
        f'<li><a href="{HARDWARE}">Senior Hardware Engineer</a></li>', ""
    )
    result = run(Pages({CATEGORY: [first, changed]}))
    assert result.status == "partial", result.reason
    assert {job["url"] for job in result.jobs} == {SOFTWARE, HARDWARE}


@pytest.mark.parametrize("failure", [
    reply("Access denied", 403),
    reply("Too many requests", 429),
    reply("Not found", 404),
    FetchError("failed", "Network/timeout failure"),
    reply("<html>Verify you are human: CAPTCHA</html>"),
    reply("<html><main><h1>Sorry, unavailable</h1></main></html>"),
], ids=["access-denied", "rate-limited", "not-found", "network-failure", "challenge", "missing-article"])
def test_bad_first_detail_preserves_other_successful_job_and_never_completes(failure):
    pages = Pages({SOFTWARE: failure})
    result = run(pages)
    assert result.status != "complete", result.reason
    assert {job["url"] for job in result.jobs} == {HARDWARE}
    assert HARDWARE in pages.urls


@pytest.mark.parametrize("body", [
    "",
    "<html><body>Verify you are human: CAPTCHA</body></html>",
    "<html><main><h1>Careers</h1><p>Annapolis Micro Systems</p></main></html>",
    f'<html><main><a href="{SOFTWARE}">Senior Software Engineer',
    fixture("careers.html").split("</main>", 1)[0],
    fixture("careers.html").replace('class="entry-title">Careers', 'class="entry-title">Products').replace(
        "See below for current openings.", "Browse our products."
    ),
], ids=["empty", "challenge", "missing-article", "unterminated-link", "truncated-main", "wrong-heading"])
def test_unverified_root_html_never_becomes_successful_empty_scan(body):
    result = run(Pages({SOURCE: body}))
    assert result.status != "complete", result.reason
    assert not result.jobs


def test_broken_linked_category_cannot_be_silently_ignored():
    result = run(Pages({CATEGORY: reply("Service unavailable", 503)}))
    assert result.status != "complete", result.reason


@pytest.mark.parametrize("url", [
    "https://example.com/careers/",
    "http://www.annapmicro.com/careers-at-annapolis-micro-systems/",
    "https://www.annapmicro.com.evil.example/careers-at-annapolis-micro-systems/",
    "https://user@www.annapmicro.com/careers-at-annapolis-micro-systems/",
    "https://www.annapmicro.com:444/careers-at-annapolis-micro-systems/",
    SOURCE + "?redirect=elsewhere",
    SOURCE + "#unexpected",
    SOURCE + "engineering-careers/",
    SOURCE + "../products/",
])
def test_adapter_rejects_unconfigured_source_before_any_network_request(url):
    pages = Pages()
    result = run(pages, url=url)
    assert result.status == "unsupported", result.reason
    assert not pages.urls


@pytest.mark.parametrize("company_id,company", [
    ("COMP-9999", COMPANY),
    (COMPANY_ID, "Different Employer"),
    ("COMP-9999", "Different Employer"),
])
def test_adapter_rejects_other_company_before_any_network_request(company_id, company):
    pages = Pages()
    result = run(pages, company_id=company_id, company=company)
    assert result.status == "unsupported", result.reason
    assert not pages.urls


def test_source_canonical_cannot_redirect_inventory_to_another_website():
    result = run(Pages({SOURCE: fixture("careers.html").replace(
        f'rel="canonical" href="{SOURCE}"',
        'rel="canonical" href="https://other.example/careers/"',
    )}))
    assert result.status != "complete", result.reason
    assert not result.jobs


def test_detail_canonical_mismatch_cannot_publish_wrong_job():
    result = run(Pages({SOFTWARE: fixture("senior-software.html").replace(
        f'rel="canonical" href="{SOFTWARE}"',
        'rel="canonical" href="https://other.example/senior-software-engineer/"',
    )}))
    assert result.status != "complete", result.reason
    assert {job["url"] for job in result.jobs} == {HARDWARE}


def test_duplicate_slash_aliases_have_one_stable_canonical_identity():
    source = fixture("careers.html").replace(
        "</main>", f'<a href="{SOFTWARE.rstrip("/")}">Senior Software Engineer</a></main>'
    )
    pages = Pages({SOURCE: source, SOFTWARE.rstrip("/"): fixture("senior-software.html")})
    first = run(pages)
    second = run(Pages())
    assert_two_full_roles(first)
    assert {job["url"]: job["posting_id"] for job in first.jobs} == {
        job["url"]: job["posting_id"] for job in second.jobs
    }


def test_distinct_canonical_role_paths_with_same_slug_keep_distinct_ids():
    other = SOURCE + "manufacturing-careers/senior-software-engineer/"
    category = fixture("engineering.html").replace(
        "</ul>", f'<li><a href="{other}">Manufacturing Engineer</a></li></ul>', 1
    )
    result = run(Pages({CATEGORY: category, other: role(other, "Manufacturing Engineer")}))
    assert result.status == "complete", result.reason
    assert len(result.jobs) == 3
    assert len({job["posting_id"] for job in result.jobs}) == 3


def test_canonical_job_identity_is_stable_when_another_role_acquires_the_same_slug():
    baseline = run(Pages())
    other = SOURCE + "manufacturing-careers/senior-software-engineer/"
    category = fixture("engineering.html").replace(
        "</ul>", f'<li><a href="{other}">Manufacturing Engineer</a></li></ul>', 1
    )
    expanded = run(Pages({CATEGORY: category, other: role(other, "Manufacturing Engineer")}))
    restored = run(Pages())
    assert baseline.status == expanded.status == restored.status == "complete"
    baseline_ids = {job["url"]: job["posting_id"] for job in baseline.jobs}
    expanded_ids = {job["url"]: job["posting_id"] for job in expanded.jobs}
    restored_ids = {job["url"]: job["posting_id"] for job in restored.jobs}
    assert baseline_ids == restored_ids
    assert all(expanded_ids[url] == identifier for url, identifier in baseline_ids.items())
    assert baseline_ids[SOFTWARE] == "engineering-careers/senior-software-engineer"


def test_no_openings_claim_appearing_on_reread_conflicts_with_unchanged_role_links():
    first = fixture("careers.html")
    changed = first.replace("See below for current openings.", "There are currently no open positions.")
    result = run(Pages({SOURCE: [first, changed]}))
    assert result.status == "partial", result.reason
    assert {job["url"] for job in result.jobs} == {SOFTWARE, HARDWARE}


def test_explicit_stable_no_openings_can_complete_with_zero_jobs():
    source = fixture("careers.html").replace(
        "See below for current openings.", "There are currently no open positions."
    ).replace(f'<a href="{SOFTWARE}">Senior Software Engineer</a>', "")
    category = fixture("engineering.html").replace(
        f'<li><a href="{SOFTWARE}">Senior Software Engineer</a></li>', ""
    ).replace(f'<li><a href="{HARDWARE}">Senior Hardware Engineer</a></li>', "")
    result = run(Pages({SOURCE: source, CATEGORY: category}))
    assert result.status == "complete", result.reason
    assert result.jobs == []


def test_unrecognized_query_role_link_cannot_silently_reduce_inventory():
    source = fixture("careers.html").replace(
        "</main>", f'<a href="{CATEGORY}engineer/?position=42">Engineer</a></main>'
    )
    pages = Pages({SOURCE: source})
    result = run(pages)
    assert result.status != "complete", result.reason
    assert not any("?" in url for url in pages.urls)


def test_offsite_and_application_links_do_not_escape_career_scope():
    source = fixture("careers.html").replace(
        "</main>",
        '<a href="https://other.example/jobs/">Partner jobs</a>'
        '<a href="mailto:recruiter@annapmicro.com">Email</a>'
        '<a href="https://www.annapmicro.com/products/">Products</a>'
        '<a href="#content">Skip to content</a></main>',
    )
    pages = Pages({SOURCE: source})
    assert_two_full_roles(run(pages))
    assert all(url.startswith(SOURCE) for url in pages.urls)
    assert not any("apply-now" in url for url in pages.urls)


def test_named_application_forms_and_numbered_apply_pages_are_not_jobs():
    application = SOURCE + "some-role/"
    numbered = SOURCE + "apply-now-2/"
    category = fixture("engineering.html").replace(
        "</main>",
        f'<a title="Apply Now" href="{application}">Complete our online application</a>'
        f'<a href="{numbered}">Complete an application</a></main>',
    )
    pages = Pages({CATEGORY: category})
    assert_two_full_roles(run(pages))
    assert application not in pages.urls
    assert numbered not in pages.urls


def test_same_scope_redirect_is_followed_and_canonical_role_deduplicated():
    alias = CATEGORY + "Senior-Software-Engineer/"
    source = fixture("careers.html").replace(SOFTWARE, alias)
    pages = Pages({SOURCE: source, alias: reply("", 301, {"Location": SOFTWARE})})
    assert_two_full_roles(run(pages))
    assert alias in pages.urls


def test_redirect_cannot_fetch_an_outside_host():
    pages = Pages({SOFTWARE: reply("", 302, {"Location": "https://other.example/job/"})})
    result = run(pages)
    assert result.status != "complete", result.reason
    assert {job["url"] for job in result.jobs} == {HARDWARE}
    assert "https://other.example/job/" not in pages.urls


@pytest.mark.parametrize("replacement", [
    '<h1 class="entry-title">Careers</h1>',
    '<h1 class="entry-title">Human Resources</h1>',
    '<h1 class="entry-title"></h1>',
])
def test_generic_page_heading_cannot_be_recorded_as_a_job_title(replacement):
    body = fixture("senior-software.html").replace(
        '<h1 class="entry-title">Senior Software Engineer</h1>', replacement
    )
    result = run(Pages({SOFTWARE: body}))
    assert result.status != "complete", result.reason
    assert {job["url"] for job in result.jobs} == {HARDWARE}


def test_page_limit_leaves_scan_partial_instead_of_truncating_inventory():
    pages = Pages()
    with patch.object(adapter, "MAX_PAGES", 2, create=True):
        result = run(pages)
    assert result.status != "complete", result.reason
    assert len(set(pages.urls)) <= 3


def test_browser_or_network_transport_is_never_created_when_injected():
    with patch.object(adapter, "CareersTransport", side_effect=AssertionError("real network")):
        assert_two_full_roles(run(Pages()))


def pipeline(tmp_path, pages):
    from job_search_helper.engine import Engine, State
    from job_search_helper.repository import MemoryRepository

    company = {
        "Company": COMPANY, "Company ID": COMPANY_ID, "Company Status": "Active",
        "ATS / Source": "Annapolis Micro careers", "Official Careers URL": SOURCE,
        "Last Checked": "2026-10-13", "Last Successful Scan": "2026-10-13T12:00:00+00:00",
    }
    repo = MemoryRepository({"Companies": [company]})
    state = State(tmp_path / "state.sqlite3")

    def fetch(source, url, company_id, company):
        return fetch_inventory(source, url, company_id, company, discovery_transport=pages)

    engine = Engine(repo, state, fetcher=fetch, error_log_path=tmp_path / "errors.jsonl")
    return repo, state, engine


def test_normal_pipeline_saves_full_inventory_count_and_successful_scan_date(tmp_path):
    repo, state, engine = pipeline(tmp_path, Pages())
    try:
        cycle = engine.start_cycle([COMPANY_ID])
        status = engine.resume(cycle)
        company = repo.read("Companies")[0]
        assert company["Scan State"] == "Complete"
        assert company["Last Inventory Count"] == 2
        assert company["Coverage Status"] == "Complete official inventory"
        assert company["Last Checked"] != "2026-10-13"
        assert company["Last Successful Scan"] != "2026-10-13T12:00:00+00:00"
        assert status["companies"][COMPANY_ID]["stage"] == "complete"
    finally:
        state.close()


def test_normal_pipeline_partial_preserves_success_date_and_never_reconciles_absences(tmp_path):
    repo, state, engine = pipeline(tmp_path, Pages({SOFTWARE: reply("Rate limited", 429)}))
    try:
        cycle = engine.start_cycle([COMPANY_ID])
        with patch.object(engine, "_reconcile_absences", wraps=engine._reconcile_absences) as reconcile:
            status = engine.resume(cycle)
        company = repo.read("Companies")[0]
        assert company["Scan State"] == "Partial"
        assert company["Last Inventory Count"] == 1
        assert company["Coverage Status"] == "Incomplete inventory"
        assert company["Last Checked"] == "2026-10-13"
        assert company["Last Successful Scan"] == "2026-10-13T12:00:00+00:00"
        assert status["companies"][COMPANY_ID]["stage"] == "partial"
        reconcile.assert_not_called()
    finally:
        state.close()

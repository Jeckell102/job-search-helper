from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import HTTPResponse
from job_search_helper.avature import SOURCE, fetch_avature
from job_search_helper.company_sources import repair_source


def listing(total, rows):
    links = "".join(f'<a href="/en_US/careers/JobDetail/{title.replace(" ", "-")}/{ident}">{title}</a>'
                    for ident, title in rows)
    return f"<main>1 - {len(rows)} of {total:,} results {links}</main>".encode()


def detail(title, req, description="Build reliable systems."):
    requisition = (f'<div class="article__content__view__field__label">Requisition #</div>'
                   f'<div class="article__content__view__field__value">{req}</div>') if req else ""
    return f'''
      <h2 class="title banner__text__title">{title}</h2>
      <article class="article article--details">
        <h3 class="article__header__text__title">General information</h3>
        {requisition}
        <div class="article__content__view__field__label">Locations</div>
        <div class="article__content__view__field__value">USA-VA-Herndon</div>
        <div class="article__content__view__field__label">Remote Type</div>
        <div class="article__content__view__field__value">Hybrid</div>
      </article>
      <article class="article article--details">
        <h3 class="article__header__text__title">Description &amp; Requirements</h3>
        <div class="article__content__view__field__value"><p>{description}</p></div>
      </article>
    '''.encode()


class ManTechTransport:
    def __init__(self, pages, details):
        self.pages = pages
        self.details = details
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        parsed = urlsplit(url)
        if "/JobDetail/" in parsed.path:
            return HTTPResponse(200, self.details[parsed.path.rsplit("/", 1)[-1]])
        offset = int(parse_qs(parsed.query)["jobOffset"][0])
        return HTTPResponse(200, self.pages[offset])


def test_mantech_avature_paginates_with_numeric_posting_and_requisition_identity():
    transport = ManTechTransport(
        {0: listing(3, [("101", "Systems Engineer"), ("102", "Cloud Engineer")]),
         2: listing(3, [("103", "Program Manager")])},
        {"101": detail("Systems Engineer", "R-101"),
         "102": detail("Cloud Engineer", "R-102"),
         "103": detail("Program Manager", "R-103")},
    )
    with patch("job_search_helper.avature.PAGE_SIZE", 2), patch("job_search_helper.avature.DETAIL_WORKERS", 1):
        result = fetch_avature(SOURCE, "COMP-0010", "ManTech", transport)

    assert result.status == "complete"
    assert [row["posting_id"] for row in result.jobs] == ["101", "102", "103"]
    assert [row["req_id"] for row in result.jobs] == ["R-101", "R-102", "R-103"]
    assert result.jobs[0]["location"] == "USA-VA-Herndon"
    assert result.jobs[0]["work_arrangement"] == "Hybrid"
    assert result.jobs[0]["description"] == "Build reliable systems."
    listing_offsets = [parse_qs(urlsplit(url).query)["jobOffset"][0]
                       for url in transport.urls if "/SearchJobs/" in url]
    assert listing_offsets == ["0", "2", "0", "2"]


def test_mantech_avature_rejects_untrusted_detail_url():
    transport = ManTechTransport(
        {0: b'of 1 results <a href="https://example.invalid/en_US/careers/JobDetail/Engineer/1">Engineer</a>'},
        {},
    )

    result = fetch_avature(SOURCE, "COMP-0010", "ManTech", transport)

    assert result.status == "partial"
    assert result.jobs == []
    assert len(transport.urls) == 1


def test_mantech_avature_requires_a_requisition_and_full_description():
    transport = ManTechTransport(
        {0: listing(1, [("101", "Systems Engineer")])},
        {"101": detail("Systems Engineer", "")},
    )

    result = fetch_avature(SOURCE, "COMP-0010", "ManTech", transport)

    assert result.status == "partial"
    assert result.jobs == []
    assert "requisition" in result.reason.lower()


def test_mantech_repair_routes_the_verified_company_to_avature():
    ats, url, note = repair_source(
        "Browser", "https://www.mantech.com/careers/why-mantech/", "COMP-0010", "ManTech"
    )

    assert ats == "Avature"
    assert url == SOURCE
    assert "Verified company source repair" in note


def test_mantech_keeps_successful_details_if_a_later_detail_is_invalid():
    transport = ManTechTransport(
        {0: listing(2, [("101", "Systems Engineer"), ("102", "Cloud Engineer")])},
        {"101": detail("Systems Engineer", "R-101"),
         "102": detail("Cloud Engineer", "")},
    )
    with patch("job_search_helper.avature.PAGE_SIZE", 2), patch("job_search_helper.avature.DETAIL_WORKERS", 1):
        result = fetch_avature(SOURCE, "COMP-0010", "ManTech", transport)

    assert result.status == "partial"
    assert [row["posting_id"] for row in result.jobs] == ["101"]


def test_mantech_rechecks_later_pages_when_count_and_first_page_stay_unchanged():
    class ChangingTransport(ManTechTransport):
        def get(self, url):
            parsed = urlsplit(url)
            if "/SearchJobs/" in parsed.path and parse_qs(parsed.query)["jobOffset"] == ["2"]:
                seen = sum("jobOffset=2" in previous for previous in self.urls)
                if seen:
                    self.pages[2] = listing(3, [("104", "New Engineer")])
            return super().get(url)

    transport = ChangingTransport(
        {0: listing(3, [("101", "Systems Engineer"), ("102", "Cloud Engineer")]),
         2: listing(3, [("103", "Program Manager")])},
        {"101": detail("Systems Engineer", "R-101"), "102": detail("Cloud Engineer", "R-102"),
         "103": detail("Program Manager", "R-103")},
    )
    with patch("job_search_helper.avature.PAGE_SIZE", 2), patch("job_search_helper.avature.DETAIL_WORKERS", 1):
        result = fetch_avature(SOURCE, "COMP-0010", "ManTech", transport)
    assert result.status == "partial"
    assert len(result.jobs) == 3


def test_mantech_detail_with_void_html_tags_preserves_description():
    body = detail("Systems Engineer", "R-101").replace(b"USA-VA-Herndon", b"USA-VA-Herndon<br>")
    transport = ManTechTransport({0: listing(1, [("101", "Systems Engineer")])}, {"101": body})
    result = fetch_avature(SOURCE, "COMP-0010", "ManTech", transport)
    assert result.status == "complete"
    assert result.jobs[0]["description"] == "Build reliable systems."


def test_avature_retries_transient_server_error_and_retains_access_blocks():
    from job_search_helper.avature import _get
    from job_search_helper.ats import FetchError
    import pytest
    class Responses:
        def __init__(self, statuses): self.statuses = iter(statuses); self.calls = 0
        def get(self, url):
            self.calls += 1
            return HTTPResponse(next(self.statuses), b"ok")
    with patch("job_search_helper.avature.time.sleep"):
        transient = Responses([503, 200])
        assert _get(transient, SOURCE) == "ok"
        assert transient.calls == 2
        exhausted = Responses([503, 503, 503])
        with pytest.raises(FetchError) as failure: _get(exhausted, SOURCE)
        assert failure.value.status == "partial" and exhausted.calls == 3
        blocked = Responses([406])
        with pytest.raises(FetchError) as failure: _get(blocked, SOURCE)
        assert failure.value.status == "blocked" and blocked.calls == 1

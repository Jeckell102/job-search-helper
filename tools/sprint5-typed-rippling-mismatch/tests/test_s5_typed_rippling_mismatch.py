"""Synthetic provider responses for the ordinary typed Rippling handoff."""
from contextlib import nullcontext
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from job_search_helper import ats, shared_boards
from job_search_helper.ats import FetchError, HTTPResponse, Inventory, fetch_inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.engine import inventory_payload


ORIGIN = "https://www.forterra.example/careers"
CONFIGURED = "https://ats.rippling.com/retired-fixture/jobs"
EXPECTED = "retired-fixture"
FOREIGN = "other-tenant"
COMPANY = "Forterra"
CID = "COMP-0066"
FIRST_POSTING = "00000000-0000-4000-8000-000000000000"


@pytest.fixture(autouse=True)
def freeze_source_and_disable_network(monkeypatch):
    from job_search_helper.company_sources import REPAIRS

    def network(*args, **kwargs):
        pytest.fail("Unexpected external transport")

    monkeypatch.setattr(socket.socket, "connect", network)
    monkeypatch.setattr(socket, "getaddrinfo", network)
    monkeypatch.setitem(REPAIRS, CID, {
        "company": COMPANY, "expected_url": ORIGIN, "ats": "Rippling",
        "url": CONFIGURED, "evidence": "synthetic test",
    })


def page_state(slug, *, page=0, total=0):
    items = [{"id": f"00000000-0000-4000-8000-{index + 20 * page:012x}", "name": "Synthetic posting"}
             for index in range(min(max(total - 20 * page, 0), 20))]
    filters = {
        "searchQuery": "", "departments": [], "workplaceType": None,
        "country": "", "state": "", "city": "", "page": page, "pageSize": 20,
    }
    listing = {
        "queryKey": ["board", slug, "job-posts", True, filters, "en-US"],
        "state": {"data": {"items": items, "totalItems": total, "page": page,
                           "pageSize": 20, "totalPages": (total + 19) // 20}},
    }
    return {"apiData": {"jobBoardSlug": slug, "jobBoard": {"slug": slug}},
            "dehydratedState": {"queries": [listing]}}


def html(state):
    value = json.dumps({"props": {"pageProps": state}})
    return f'<script type="application/json" id="__NEXT_DATA__">{value}</script>'.encode()


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def direct(*responses, route=ORIGIN, provider="Rippling"):
    transport = Transport(responses)
    result = fetch_inventory(provider, route, CID, COMPANY, transport=transport)
    return result, transport.calls


def mismatch_response(**options):
    return HTTPResponse(200, html(page_state(FOREIGN, total=1)), **{
        "response_url": CONFIGURED, **options,
    })


def test_exact_dispatch_yields_only_the_bounded_typed_observation():
    assert Path(ats.__file__).parent == Path(__file__).parents[1] / "src/job_search_helper"
    response = mismatch_response()
    result, calls = direct(response)
    assert calls == [CONFIGURED]
    assert result.status == "partial" and result.ats == "Rippling" and result.jobs == []
    assert result.reason.endswith("Rippling board identity mismatch.")
    assert result.outcome_failure is None and result.verified_zero is None
    record = result.rippling_tenant_mismatch.to_record()
    assert record == {
        "schema": "rippling-tenant-mismatch-v1", "configured_url": CONFIGURED,
        "expected_slug": EXPECTED, "observed_slug": FOREIGN, "response_sha256": sha256(response.body).hexdigest(),
    }
    assert ats.validate_rippling_tenant_mismatch(record) == result.rippling_tenant_mismatch
    payload = inventory_payload(result, {"Company ID": CID, "Official Careers URL": ORIGIN})
    assert "rippling_tenant_mismatch" not in payload
    assert "response_sha256" not in json.dumps(payload)


@pytest.mark.parametrize("field,value", [
    ("schema", "unreviewed"), ("configured_url", CONFIGURED + "?page=0"),
    ("configured_url", CONFIGURED.replace("ats.", "ats.us1.")),
    ("expected_slug", "other-route"), ("observed_slug", EXPECTED.upper()),
    ("observed_slug", "x" * 101), ("observed_slug", ["wrong-shape"]),
    ("response_sha256", "A" * 64), ("response_sha256", {}),
    ("unexpected", "unbounded"),
])
def test_typed_record_rejects_invalid_schema_and_binding(field, value):
    result, _ = direct(mismatch_response())
    record = {**result.rippling_tenant_mismatch.to_record(), field: value}
    assert ats.validate_rippling_tenant_mismatch(record) is None


@pytest.mark.parametrize("status,expected_status", [(200.0, "partial"), (202, "partial"), (302, "partial"),
                                                     (403, "blocked"), (429, "partial"), (503, "partial")])
def test_existing_nonexact_http_and_access_statuses_win(status, expected_status):
    response = HTTPResponse(status, html(page_state(FOREIGN)), response_url=CONFIGURED)
    result, calls = direct(response)
    assert calls == [CONFIGURED] and result.status == expected_status
    assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("raw", [
    b"<title>Verify you are human</title>",
    b'<script type="application/json" id="__NEXT_DATA__">{invalid}</script>',
    b'<script type="application/json" id="__NEXT_DATA__">{"props":[]}</script>',
])
def test_challenges_and_malformed_html_cannot_authorize_capture(raw):
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.rippling_tenant_mismatch is None
    assert result.status == ("blocked" if b"Verify" in raw else "partial")


@pytest.mark.parametrize("mutation", ["disagree", "case-only", "missing-query", "filtered", "duplicate-key",
                                     "wrong-page", "malformed-items", "non-rippling-query"])
def test_partial_foreign_identity_requires_complete_closed_page_zero_shape(mutation):
    state = page_state(FOREIGN, total=1)
    listing = state["dehydratedState"]["queries"][0]
    if mutation == "disagree":
        state["apiData"]["jobBoard"]["slug"] = "different-third-tenant"
    elif mutation == "case-only":
        state = page_state(EXPECTED.upper(), total=1)
    elif mutation == "missing-query":
        state["dehydratedState"]["queries"] = []
    elif mutation == "filtered":
        listing["queryKey"][4]["country"] = "US"
    elif mutation == "wrong-page":
        listing["state"]["data"]["page"] = 1
    elif mutation == "malformed-items":
        listing["state"]["data"]["items"] = {"id": "invalid"}
    elif mutation == "non-rippling-query":
        listing["queryKey"][0] = "another-provider"
    raw = html(state)
    if mutation == "duplicate-key":
        raw = raw.replace(b'"jobBoardSlug":', b'"jobBoardSlug": "duplicate", "jobBoardSlug":', 1)
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.status == "partial"
    assert result.reason.endswith("Rippling board identity mismatch.")
    assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("location,field,value", [
    ("filters", "page", False), ("filters", "page", 0.0), ("filters", "pageSize", 20.0),
    ("data", "page", False), ("data", "page", 0.0), ("data", "pageSize", 20.0),
    ("data", "totalItems", True), ("data", "totalItems", 1.0),
    ("data", "totalPages", True), ("data", "totalPages", 1.0),
    ("posting", "id", " "), ("posting", "id", "\t"), ("posting", "id", "arbitrary-posting-id"),
    ("posting", "id", 1), ("posting", "id", " " + FIRST_POSTING),
    ("posting", "name", None), ("posting", "name", "  "), ("posting", "name", 1),
])
def test_typed_numeric_metadata_and_posting_identifiers_are_exact(location, field, value):
    state = page_state(FOREIGN, total=1)
    query = state["dehydratedState"]["queries"][0]
    data = query["state"]["data"]
    fields = {"filters": query["queryKey"][4], "data": data, "posting": data["items"][0]}
    fields[location][field] = value
    result, _ = direct(HTTPResponse(200, html(state), response_url=CONFIGURED))
    assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
    assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("tag,legacy_reason", [
    (tag, "Rippling board identity mismatch.") for tag in ("template", "noscript", "svg")
] + [
    (tag, "Public Next.js board state missing or ambiguous.") for tag in ("textarea", "title", "iframe")
])
def test_inert_next_data_cannot_establish_tenant_observation(tag, legacy_reason):
    raw = f"<{tag}>".encode() + html(page_state(FOREIGN, total=1)) + f"</{tag}>".encode()
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.status == "partial" and result.reason.endswith(legacy_reason)
    assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("replacement", [
    b'id="decoy" id="__NEXT_DATA__"', b'id="__NEXT_DATA__" id="__NEXT_DATA__"',
    b'type="application/json" id="__NEXT_DATA__" src="foreign.js"',
    b'type="application/ld+json" id="__NEXT_DATA__"',
])
def test_ambiguous_next_data_attributes_cannot_establish_tenant_observation(replacement):
    raw = html(page_state(FOREIGN, total=1)).replace(b'id="__NEXT_DATA__"', replacement)
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.status == "partial" and result.rippling_tenant_mismatch is None


def test_duplicate_active_document_id_stays_an_ordinary_partial():
    raw = b'<div id="__NEXT_DATA__"></div>' + html(page_state(FOREIGN, total=1))
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
    assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("title", ["Verify you are human", "Human verification", "Just a moment",
                                  "CAPTCHA", "Access denied"])
def test_active_challenge_title_after_ordinary_prefix_refuses_typed_evidence(title):
    raw = b" " * 8192 + f"<title>{title}</title>".encode() + html(page_state(FOREIGN, total=1))
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
    assert result.rippling_tenant_mismatch is None


def test_ordinary_active_title_heading_keeps_valid_typed_evidence():
    raw = b"<title>Careers and open roles</title>" + html(page_state(FOREIGN, total=1))
    result, _ = direct(HTTPResponse(200, raw, response_url=CONFIGURED))
    assert result.rippling_tenant_mismatch.response_sha256 == sha256(raw).hexdigest()


def test_missing_posting_name_and_case_variant_uuid_ambiguity_refuse_typed_evidence():
    missing = page_state(FOREIGN, total=1)
    del missing["dehydratedState"]["queries"][0]["state"]["data"]["items"][0]["name"]
    repeated = page_state(FOREIGN, total=2)
    items = repeated["dehydratedState"]["queries"][0]["state"]["data"]["items"]
    items[0]["id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    items[1]["id"] = items[0]["id"].upper()
    for state in (missing, repeated):
        result, _ = direct(HTTPResponse(200, html(state), response_url=CONFIGURED))
        assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
        assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("mutation", ["private-flag", "expected-query", "third-query", "duplicate-foreign-query"])
def test_typed_observation_requires_one_foreign_public_listing_query(mutation):
    state = page_state(FOREIGN, total=1)
    queries = state["dehydratedState"]["queries"]
    if mutation == "private-flag":
        queries[0]["queryKey"][3] = False
    else:
        competitor = deepcopy(queries[0])
        competitor["queryKey"][1] = {
            "expected-query": EXPECTED, "third-query": "third-tenant", "duplicate-foreign-query": FOREIGN,
        }[mutation]
        queries.append(competitor)
    result, _ = direct(HTTPResponse(200, html(state), response_url=CONFIGURED))
    assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
    assert result.rippling_tenant_mismatch is None


def test_plain_listing_keeps_existing_false_scope_flag_behavior():
    state = page_state(EXPECTED)
    state["dehydratedState"]["queries"][0]["queryKey"][3] = False
    response = HTTPResponse(200, html(state), response_url=CONFIGURED)
    result, _ = direct(response, response)
    assert result.status == "complete" and result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("response_url", [None, "https://ats.rippling.com/other-tenant/jobs",
                                          CONFIGURED + "?page=0", CONFIGURED + "/"])
def test_initial_requested_route_requires_exact_observed_response_url(response_url):
    result, _ = direct(mismatch_response(response_url=response_url))
    assert result.status == "partial" and result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("route,provider", [
    ("https://ats.us1.rippling.com/retired-fixture/jobs", "Rippling"),
    (CONFIGURED + "/", "Rippling"),
    (CONFIGURED, "Other provider"),
])
def test_route_aliases_and_foreign_provider_remain_ordinary_partial(route, provider):
    result, calls = direct(mismatch_response(), route=route, provider=provider)
    assert calls == [CONFIGURED]
    assert result.status == "partial" and result.rippling_tenant_mismatch is None


def test_employer_discovery_path_remains_ordinary_partial():
    employer = "https://www.example.org/careers"
    link = f'<a href="{CONFIGURED}">Open jobs</a>'.encode()
    result = shared_boards.fetch_shared(
        "Rippling", employer, CID, COMPANY, transport=Transport([mismatch_response()]),
        pages=Transport([HTTPResponse(200, link, response_url=employer)]),
    )
    assert result.status == "partial" and result.rippling_tenant_mismatch is None


def test_later_page_mismatch_stays_an_ordinary_partial():
    paged = CONFIGURED + "?page=1"
    result, calls = direct(
        HTTPResponse(200, html(page_state(EXPECTED, total=21)), response_url=CONFIGURED),
        mismatch_response(response_url=paged),
    )
    assert calls == [CONFIGURED, paged]
    assert result.status == "partial" and result.rippling_tenant_mismatch is None


def test_final_list_reread_mismatch_stays_an_ordinary_partial(monkeypatch):
    monkeypatch.setattr(shared_boards, "posting", lambda b, t, entry, cid, company: {"posting_id": entry["id"]})
    result, calls = direct(
        HTTPResponse(200, html(page_state(EXPECTED, total=1)), response_url=CONFIGURED), mismatch_response(),
    )
    assert calls == [CONFIGURED, CONFIGURED]
    assert result.status == "partial" and result.jobs == [{"posting_id": FIRST_POSTING}]
    assert result.rippling_tenant_mismatch is None


def test_existing_matching_zero_listing_remains_complete():
    response = HTTPResponse(200, html(page_state(EXPECTED)), response_url=CONFIGURED)
    result, calls = direct(response, response)
    assert calls == [CONFIGURED, CONFIGURED]
    assert result.status == "complete" and not result.jobs
    assert result.rippling_tenant_mismatch is None and result.verified_zero is None


def test_builtin_direct_transport_binds_the_final_response_url(monkeypatch):
    response = mismatch_response()
    source = SimpleNamespace(status=200, url=CONFIGURED, headers={}, read=lambda _size: response.body)
    opener = SimpleNamespace(open=lambda _request, **_options: nullcontext(source))
    monkeypatch.setattr(shared_boards.Transport, "_opener", lambda self: opener)
    result = fetch_inventory("Rippling", ORIGIN, CID, COMPANY)
    assert result.rippling_tenant_mismatch.response_sha256 == sha256(response.body).hexdigest()


def test_existing_typed_temporary_failure_survives_direct_dispatch():
    failure = ats.outcome_failure("temporary_transport", "network_retry_exhausted")
    result, _ = direct(FetchError("partial", "Time budget elapsed", outcome_failure=failure))
    assert result.outcome_failure == failure
    assert result.rippling_tenant_mismatch is None


def wrapped_direct(response):
    transport = Transport([response])
    return with_browser_fallback(
        lambda provider, url, cid, company: fetch_inventory(provider, url, cid, company, transport=transport)
    )


class BrowserPage:
    def __init__(self, body, final_url, *, redirected=False, raw=None, headers=None):
        self.final_url = final_url
        self.body = body
        self.redirected = redirected
        self.raw = body if raw is None else raw
        self.headers = headers or {}

    def goto(self, url, **kwargs):
        assert url == CONFIGURED
        self.url = self.final_url
        request = SimpleNamespace(redirected_from=object() if self.redirected else None)
        return SimpleNamespace(status=200, url=self.url, request=request, headers=self.headers, body=self.raw_body)

    def content(self):
        return self.body.decode()

    def raw_body(self):
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


def use_browser_page(monkeypatch, page):
    context = SimpleNamespace(new_page=lambda: page)
    browser = SimpleNamespace(new_context=lambda: context, close=lambda: None)
    launcher = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    import playwright.sync_api
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: nullcontext(launcher))


@pytest.mark.parametrize("browser_url,redirected,foreign,typed", [
    (CONFIGURED, False, FOREIGN, True),
    (CONFIGURED, False, "third-rippling-tenant", False),
    (CONFIGURED, True, FOREIGN, False),
    (CONFIGURED + "/", False, FOREIGN, False),
])
def test_enabled_browser_reconciles_only_the_same_exact_initial_tenant(
        monkeypatch, browser_url, redirected, foreign, typed):
    response = mismatch_response()
    page = BrowserPage(html(page_state(foreign, total=1)) + b"<!-- rendered suffix -->",
                       browser_url, redirected=redirected)
    use_browser_page(monkeypatch, page)
    result = wrapped_direct(response)("Rippling", ORIGIN, CID, COMPANY)
    assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
    if typed:
        assert result.rippling_tenant_mismatch.response_sha256 == sha256(response.body).hexdigest()
    else:
        assert result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("original", ["expected", "other-foreign", "challenge", "missing",
                                     "declared-too-large", "actual-too-large"])
def test_browser_rendered_mismatch_cannot_vouch_for_an_unverified_original_response(monkeypatch, original):
    rendered = html(page_state(FOREIGN, total=1))
    headers = {}
    raw = {
        "expected": html(page_state(EXPECTED)),
        "other-foreign": html(page_state("third-foreign")),
        "challenge": b"<title>Verify you are human</title>",
        "missing": RuntimeError("Navigation body unavailable"),
        "declared-too-large": rendered,
        "actual-too-large": b"x" * (shared_boards.MAX_RESPONSE_BYTES + 1),
    }[original]
    if original == "declared-too-large":
        headers = {"Content-Length": str(shared_boards.MAX_RESPONSE_BYTES + 1)}
    use_browser_page(monkeypatch, BrowserPage(rendered, CONFIGURED, raw=raw, headers=headers))
    result = wrapped_direct(mismatch_response())("Rippling", ORIGIN, CID, COMPANY)
    assert result.status == "partial" and result.reason.endswith("Rippling board identity mismatch.")
    assert result.rippling_tenant_mismatch is None


def test_browser_only_record_hashes_original_navigation_bytes(monkeypatch):
    raw = html(page_state(FOREIGN, total=1))
    rendered = raw + b"<!-- browser-produced markup -->"
    use_browser_page(monkeypatch, BrowserPage(rendered, CONFIGURED, raw=raw))
    result = shared_boards.fetch_shared_browser("Rippling", CONFIGURED, CID, COMPANY)
    assert result.rippling_tenant_mismatch.response_sha256 == sha256(raw).hexdigest()


@pytest.mark.parametrize("status,category,code", [
    ("complete", None, None), ("blocked", "access_denied", "human_verification"),
    ("partial", "temporary_transport", "retryable_http_status"), ("partial", None, None),
])
def test_fallback_selection_and_existing_outcomes_are_unchanged(monkeypatch, status, category, code):
    envelope = ats.outcome_failure(category, code) if category else None
    fallback = Inventory(status, reason="existing fallback result", source_url=CONFIGURED, ats="Rippling",
                         outcome_failure=envelope)
    monkeypatch.setattr(shared_boards, "fetch_shared_browser", lambda *args, **kwargs: fallback)
    result = wrapped_direct(mismatch_response())("Rippling", ORIGIN, CID, COMPANY)
    assert result is fallback and result.reason.endswith("existing fallback result")
    assert result.outcome_failure == envelope and result.rippling_tenant_mismatch is None


@pytest.mark.parametrize("status,category,code", [
    ("blocked", "access_denied", "public_access_denied"),
    ("partial", "temporary_transport", "network_retry_exhausted"),
    ("partial", None, None),
])
def test_browser_candidate_cannot_promote_a_different_initial_failure(monkeypatch, status, category, code):
    envelope = ats.outcome_failure(category, code) if category else None
    browser_candidate, _ = direct(mismatch_response())
    monkeypatch.setattr(shared_boards, "fetch_shared_browser", lambda *args, **kwargs: browser_candidate)
    original = FetchError(status, "ordinary initial failure", outcome_failure=envelope)
    final = wrapped_direct(original)("Rippling", ORIGIN, CID, COMPANY)
    assert final is browser_candidate
    assert final.rippling_tenant_mismatch is None

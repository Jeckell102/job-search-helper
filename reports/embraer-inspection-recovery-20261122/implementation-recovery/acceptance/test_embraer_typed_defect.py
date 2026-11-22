"""Future acceptance baseline for the narrow Embraer brand-heading repair."""
import json

from job_search_helper.ats import BREEZY_EMBRAER_HEADING_CODE, HTTPResponse, validate_outcome_failure
from job_search_helper import shared_boards


BOARD = 'https://embraer.breezy.hr/'


class Transport:
    def __init__(self, listings, details):
        self.listings, self.details, self.listing_reads = listings, details, 0

    def get(self, url):
        if url == BOARD + 'json':
            self.listing_reads += 1
            return HTTPResponse(200, self.listings)
        return HTTPResponse(200, self.details[url])


def _entry(ident, title):
    return {'id': ident, 'name': title, 'url': BOARD + 'p/' + ident + '-role',
            'company': {'friendly_id': 'embraer'}, 'locations': []}


def _body(url, title, *, brand=False, description=True):
    headings = (f'<a class="brand"><h1>Embraer</h1></a><div class="banner"><h1>{title}</h1></div>'
                if brand else f'<div class="banner"><h1>{title}</h1></div>')
    content = '<div class="description"><p>fixture description</p></div>' if description else ''
    return (f'<meta property="og:url" content="{url}">{headings}{content}').encode()


def _two_listings():
    good, affected = _entry('111111111111', 'Good role'), _entry('222222222222', 'Affected role')
    return good, affected, json.dumps([good, affected]).encode()


def test_valid_embraer_brand_heading_is_complete_with_stable_full_inventory():
    good, affected, listings = _two_listings()
    transport = Transport(listings, {good['url']: _body(good['url'], good['name']),
                                     affected['url']: _body(affected['url'], affected['name'], brand=True)})
    result = shared_boards.fetch_shared('Breezy HR', BOARD, 'COMP-0634', 'Embraer', transport)
    assert result.status == 'complete' and result.outcome_failure is None
    assert transport.listing_reads == 2 and len(result.jobs) == 2
    by_url = {job['url']: job for job in result.jobs}
    assert by_url[affected['url']]['title'] == affected['name']
    assert by_url[affected['url']]['description'] == 'fixture description'


def test_only_posting_boundary_typed_failure_produces_isolated_envelope(monkeypatch):
    good, affected, listings = _two_listings()
    actual = shared_boards.posting
    def typed_boundary(board, transport, entry, company_id, company):
        if entry['id'] == affected['id']:
            raise shared_boards._embraer_heading_failure()
        return actual(board, transport, entry, company_id, company)
    monkeypatch.setattr(shared_boards, 'posting', typed_boundary)
    result = shared_boards.fetch_shared('Breezy HR', BOARD, 'COMP-0634', 'Embraer',
                                        Transport(listings, {good['url']: _body(good['url'], good['name']),
                                                             affected['url']: _body(affected['url'], affected['name'], brand=True)}))
    assert result.status == 'partial' and len(result.jobs) == 1 and result.outcome_failure == validate_outcome_failure(result.outcome_failure)
    assert result.outcome_failure['evidence_code'] == BREEZY_EMBRAER_HEADING_CODE
    assert result.outcome_failure['evidence']['advertised_total'] == 2
    assert result.outcome_failure['evidence']['detail_failure_count'] == 1


def test_malformed_or_unscoped_detail_failure_stays_untyped():
    good, affected, listings = _two_listings()
    malformed = shared_boards.fetch_shared('Breezy HR', BOARD, 'COMP-0634', 'Embraer',
        Transport(listings, {good['url']: _body(good['url'], good['name']),
                             affected['url']: _body(affected['url'], affected['name'], description=False)}))
    assert malformed.status == 'partial' and malformed.outcome_failure is None
    foreign = shared_boards.fetch_shared('Breezy HR', BOARD, 'COMP-0000', 'Other',
        Transport(listings, {good['url']: _body(good['url'], good['name']),
                             affected['url']: _body(affected['url'], affected['name'], brand=True)}))
    assert foreign.status == 'partial' and foreign.outcome_failure is None

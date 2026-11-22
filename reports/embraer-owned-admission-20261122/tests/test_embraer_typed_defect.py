from job_search_helper.ats import BREEZY_EMBRAER_HEADING_CODE, HTTPResponse, validate_outcome_failure
from job_search_helper.shared_boards import fetch_shared


BOARD = 'https://embraer.breezy.hr/'


class Transport:
    def __init__(self, listings, details):
        self.listings, self.details = listings, details
        self.listing_reads = 0

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


def test_only_stable_full_embraer_heading_failures_produce_typed_envelope():
    good, bad = _entry('111111111111', 'Good role'), _entry('222222222222', 'Affected role')
    import json
    listings = json.dumps([good, bad]).encode()
    transport = Transport(listings, {
        good['url']: _body(good['url'], good['name']),
        bad['url']: _body(bad['url'], bad['name'], brand=True),
    })
    result = fetch_shared('Breezy HR', BOARD, 'COMP-0634', 'Embraer', transport)
    assert result.status == 'partial' and len(result.jobs) == 1 and transport.listing_reads == 2
    assert result.outcome_failure == validate_outcome_failure(result.outcome_failure)
    assert result.outcome_failure['evidence_code'] == BREEZY_EMBRAER_HEADING_CODE
    evidence = result.outcome_failure['evidence']
    assert evidence['advertised_total'] == 2 and evidence['detail_failure_count'] == 1
    assert 'Affected role' not in repr(evidence) and bad['url'] not in repr(evidence)


def test_mixed_or_unscoped_detail_failure_stays_untyped():
    good, bad = _entry('111111111111', 'Good role'), _entry('222222222222', 'Affected role')
    import json
    listings = json.dumps([good, bad]).encode()
    transport = Transport(listings, {
        good['url']: _body(good['url'], good['name']),
        bad['url']: _body(bad['url'], bad['name'], description=False),
    })
    result = fetch_shared('Breezy HR', BOARD, 'COMP-0634', 'Embraer', transport)
    assert result.status == 'partial' and result.outcome_failure is None
    other = fetch_shared('Breezy HR', BOARD, 'COMP-0000', 'Other', Transport(listings, {
        good['url']: _body(good['url'], good['name']),
        bad['url']: _body(bad['url'], bad['name'], brand=True),
    }))
    assert other.status == 'partial' and other.outcome_failure is None

import copy
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest

from job_search_helper import bosch_rexroth as rex, shared_boards as boards
from job_search_helper.ats import HTTPResponse, fetch_inventory


def card(ident='1', entity=rex.ENTITY, country='us', brand='Rexroth'):
    return {'id': ident, 'name': 'Applications Engineer ' + ident, 'refNumber': 'REF' + ident,
            'company': {'identifier': 'BoschGroup'}, 'visibility': 'PUBLIC',
            'location': {'country': country, 'fullLocation': 'Bethlehem, PA, United States'},
            'customField': [{'fieldId': rex.ENTITY_FIELD, 'valueLabel': entity},
                            {'fieldId': 'brand', 'valueLabel': brand}]}


def detail(entry):
    result = copy.deepcopy(entry)
    result.update(active=True, postingUrl='https://jobs.smartrecruiters.com/BoschGroup/' + entry['id'] + '-applications-engineer',
                  jobAd={'sections': {'jobDescription': {'title': 'Job Description', 'text': '<p>Lead customer automation projects.</p>'}}})
    return result


class Feed:
    def __init__(self, cohorts, details=None):
        self.cohorts = cohorts
        self.round = -1
        self.calls = []
        self.details = details or {e['id']: detail(e) for cohort in cohorts for e in cohort}
        self.mutate_page = lambda p: p

    def get(self, url):
        self.calls.append(url)
        parsed = urlsplit(url)
        if parsed.path == urlsplit(rex.API).path:
            query = parse_qs(parsed.query)
            assert query['country'] == ['us']
            offset = int(query['offset'][0])
            if offset == 0:
                self.round += 1
            entries = self.cohorts[min(self.round, len(self.cohorts) - 1)]
            data = self.mutate_page({'offset': offset, 'limit': 100, 'totalFound': len(entries), 'content': entries[offset:offset + 100]})
        else:
            data = self.details[parsed.path.rsplit('/', 1)[-1]]
        if isinstance(data, HTTPResponse):
            return data
        return HTTPResponse(200, json.dumps(data).encode())

    @property
    def detail_ids(self):
        return [url.rsplit('/', 1)[-1] for url in self.calls if '?' not in url]


def scan(feed, **kwargs):
    return fetch_inventory('SmartRecruiters', rex.SOURCE, rex.COMPANY_ID, rex.COMPANY, feed, **kwargs)


def test_filters_before_details_and_retains_rexroth_other_brands():
    entries = [card(), card('2', brand='Bosch Group'), card('3', brand='Hägglunds'), card('4', 'Robert Bosch LLC')]
    feed = Feed([entries])
    result = scan(feed)
    assert result.status == 'complete', result.reason
    assert feed.detail_ids == ['1', '2', '3']
    assert {j['legal_entity'] for j in result.jobs} == {rex.ENTITY}
    assert {j['req_id'] for j in result.jobs} == {'REF1', 'REF2', 'REF3'}
    assert result.source_url == rex.SOURCE
    assert not result.browser_fallback_allowed


def test_all_pages_are_rechecked_even_when_only_later_page_has_rexroth():
    entries = [card(str(i), 'Robert Bosch LLC') for i in range(100)] + [card('100')]
    feed = Feed([entries])
    result = scan(feed)
    assert result.status == 'complete', result.reason
    assert feed.detail_ids == ['100']
    assert sum('offset=100' in url for url in feed.calls) == 2


@pytest.mark.parametrize('mutation', [
    lambda e: e['location'].update(country='de'),
    lambda e: e.update(customField=[]),
    lambda e: e['customField'].append({'fieldId': rex.ENTITY_FIELD, 'valueLabel': rex.ENTITY}),
    lambda e: e.update(visibility='INTERNAL'),
    lambda e: e['company'].update(identifier='Other'),
    lambda e: e.update(id='../outside'),
])
def test_invalid_listing_scope_cannot_complete(mutation):
    entry = card(); mutation(entry)
    result = scan(Feed([[entry]]))
    assert result.status == 'partial'
    assert result.jobs == []
    assert not result.browser_fallback_allowed


@pytest.mark.parametrize('mutation', [
    lambda d: d['customField'][0].update(valueLabel='Robert Bosch LLC'),
    lambda d: d['location'].update(country='ca'),
    lambda d: d.update(active=False),
    lambda d: d.update(id='2'),
    lambda d: d.update(name='Other job'),
    lambda d: d.update(refNumber='OTHER'),
    lambda d: d.update(postingUrl='https://jobs.smartrecruiters.com/Other/1-job'),
    lambda d: d['jobAd']['sections']['jobDescription'].update(text=''),
    lambda d: d['location'].update(fullLocation=''),
])
def test_invalid_details_excluded_but_verified_jobs_preserved(mutation):
    entries = [card(), card('2')]
    d = detail(entries[0]); mutation(d)
    result = scan(Feed([entries], {'1': d, '2': detail(entries[1])}))
    assert result.status == 'partial'
    assert [j['posting_id'] for j in result.jobs] == ['2']


@pytest.mark.parametrize('mutation', [
    lambda p: dict(p, totalFound=p['totalFound']+1),
    lambda p: dict(p, limit=99),
    lambda p: dict(p, offset=1),
    lambda p: dict(p, totalFound=True),
    lambda p: dict(p, content='invalid'),
])
def test_malformed_pagination_cannot_complete(mutation):
    feed = Feed([[card()]]); feed.mutate_page = mutation
    assert scan(feed).status == 'partial'


def test_duplicate_ids_cannot_complete():
    assert scan(Feed([[card(), card()]])).status == 'partial'


def test_unrelated_bosch_churn_does_not_restart_rexroth_details():
    feed = Feed([[card(), card('2', 'Robert Bosch LLC')], [card(), card('3', 'Robert Bosch LLC')]])
    assert scan(feed).status == 'complete'
    assert feed.detail_ids == ['1']


def test_removal_and_addition_reconcile_without_refetching_unchanged_jobs():
    feed = Feed([[card(), card('2')], [card(), card('3')]])
    result = scan(feed)
    assert result.status == 'complete', result.reason
    assert {j['posting_id'] for j in result.jobs} == {'1', '3'}
    assert feed.detail_ids == ['1', '2', '3']


def test_persistent_scoped_drift_stays_partial():
    feed = Feed([[card(str(i))] for i in range(5)])
    assert scan(feed).status == 'partial'


def test_empty_scope_rechecked_before_completion():
    feed = Feed([[card('2', 'Robert Bosch LLC')]])
    result = scan(feed)
    assert result.status == 'complete'
    assert not result.jobs
    assert len(feed.calls) == 2


def test_blocked_detail_stops_and_retains_verified_work():
    entries = [card(), card('2'), card('3')]
    feed = Feed([entries], {'1': detail(entries[0]), '2': HTTPResponse(403, b'Forbidden'), '3': detail(entries[2])})
    result = scan(feed)
    assert result.status == 'blocked'
    assert [j['posting_id'] for j in result.jobs] == ['1']
    assert feed.detail_ids == ['1', '2']


class Progress:
    def __init__(self):
        self.saved = {}; self.policy = ''; self.sources = []
    def __call__(self, source):
        self.sources.append(source); return self
    def completed_details(self, policy):
        return self.saved if policy == self.policy else {}
    def save_detail(self, entry, row, policy):
        self.policy = policy; self.saved[entry['id']] = (entry, row)


def test_resume_reuses_only_matching_scoped_details():
    progress = Progress()
    assert scan(Feed([[card()]]), progress_factory=progress).status == 'complete'
    feed = Feed([[card(), card('2')]])
    result = scan(feed, progress_factory=progress)
    assert result.status == 'complete'
    assert feed.detail_ids == ['2']
    assert set(progress.sources) == {rex.SCOPE}


def test_cooperative_transport_uses_same_validations():
    feed = Feed([[card(), card('2', 'Robert Bosch LLC')]])
    transport = boards.Transport(rex.BOARD)
    with patch.object(transport, 'get', side_effect=feed.get):
        result = scan(transport)
    assert result.status == 'complete'
    assert feed.detail_ids == ['1']


@pytest.mark.parametrize('source', sorted(rex.SOURCES))
def test_verified_sources_route_to_scoped_adapter(source):
    result = fetch_inventory('SmartRecruiters', source, rex.COMPANY_ID, rex.COMPANY, Feed([[card()]]))
    assert result.status == 'complete'


@pytest.mark.parametrize('source', [rex.SOURCE+'?q=sales', rex.SOURCE.replace('https:', 'http:'),
                                    'https://careers.smartrecruiters.com/Other',
                                    'https://jobs.bosch.com/en', rex.SOURCE+'#filter'])
def test_changed_source_never_expands_to_parent(source):
    feed = Feed([[card()]])
    result = fetch_inventory('SmartRecruiters', source, rex.COMPANY_ID, rex.COMPANY, feed)
    assert result.status == 'unsupported'
    assert not result.browser_fallback_allowed
    assert not feed.calls


def test_wrapper_requires_exact_company_identity():
    assert rex.fetch_bosch_rexroth(rex.SOURCE, 'OTHER', rex.COMPANY).status == 'unsupported'
    assert rex.fetch_bosch_rexroth(rex.SOURCE, rex.COMPANY_ID, 'Bosch').status == 'unsupported'


def test_only_pinned_bosch_us_listing_route_is_added():
    url = rex.API + '?limit=100&offset=0&country=us'
    assert boards.allowed(rex.BOARD, url)
    for bad in [url.replace('country=us', 'country=de'), url+'&q=engineer', url.replace('/postings?', '/postings/1?'),
                url.replace('api.smartrecruiters.com', 'example.com'), url+'#x', url.replace('https:', 'http:')]:
        assert not boards.allowed(rex.BOARD, bad)
    assert not boards.allowed(rex.BOARD, url, {})
    assert not boards.allowed(boards.board_link('https://careers.smartrecruiters.com/Example'), url)


def test_scoped_source_not_comparable_to_legacy_parent_for_closure():
    from job_search_helper.engine import _inventory_source
    assert _inventory_source(rex.SOURCE) != _inventory_source(rex.BOARD.url)


def test_live_legal_notice_with_role_description_in_company_section():
    from pathlib import Path
    full = json.loads((Path(__file__).parent/'fixtures/bosch_rexroth/legal-notice.json').read_text())
    entry = {k: full[k] for k in ('id','name','refNumber','company','visibility','location','customField')}
    result = scan(Feed([[entry]], {entry['id']: full}))
    assert result.status == 'complete', result.reason
    assert result.jobs[0]['description_source'] == 'companyDescription'
    assert 'C/C++ and MATLAB Simulink' in result.jobs[0]['description']
    assert result.jobs[0]['description'].count('Bosch Rexroth Corporation seeks') == 1


@pytest.mark.parametrize('bad_value', ['generic boilerplate', 'wrong ref', 'wrong title'])
def test_alternate_section_requires_real_role_evidence(bad_value):
    from pathlib import Path
    full = json.loads((Path(__file__).parent/'fixtures/bosch_rexroth/legal-notice.json').read_text())
    entry = {k: copy.deepcopy(full[k]) for k in ('id','name','refNumber','company','visibility','location','customField')}
    section = full['jobAd']['sections']['companyDescription']
    if bad_value == 'generic boilerplate':
        section['text'] = ('Bosch Rexroth Corporation is an engineering employer. '*30)
    elif bad_value == 'wrong ref':
        section['text'] = section['text'].replace('REF286610T', 'REFOTHER')
    else:
        section['text'] = section['text'].replace('Controls Systems Engineer', 'Other Position')
    result = scan(Feed([[entry]], {entry['id']: full}))
    assert result.status == 'partial'
    assert not result.jobs

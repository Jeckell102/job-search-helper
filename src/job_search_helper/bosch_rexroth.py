"""U.S. Bosch Rexroth inventory from Bosch's public SmartRecruiters feed.

Read every U.S. listing card, select by provider legal entity (not brand or
keywords), then fetch only Rexroth descriptions. Recheck scoped membership and
metadata before declaring completion. Unrelated Bosch edits do not restart it.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
from threading import Event

from .ats import FetchError, HTTPResponse, Inventory, text
from .cooperative_fetch import iter_details
from .derived_cache import content_digest
from . import shared_boards as boards

COMPANY_ID = 'COMP-0571'
COMPANY = 'Bosch Rexroth'
SOURCE = 'https://www.boschrexroth.com/en/us/jobs-and-career/job-opportunities/'
SOURCES = frozenset({
    SOURCE.rstrip('/'),
    'https://www.boschrexroth.com/en/us/jobs-and-career',
    'https://careers.smartrecruiters.com/BoschGroup',
    'https://careers.smartrecruiters.com/BoschGroup/us',
})
API = 'https://api.smartrecruiters.com/v1/companies/BoschGroup/postings'
BOARD = boards.board_link('https://careers.smartrecruiters.com/BoschGroup')
ENTITY_FIELD = '586a9995e4b0daa006ae1078'
ENTITY = 'Bosch Rexroth Corporation'
# Scope-specific checkpoint identity prevents reuse of the old parent inventory.
SCOPE = API + '?country=us&scope=bosch-rexroth-corporation'


def _entity(entry):
    fields = entry.get('customField')
    if not isinstance(fields, list):
        raise FetchError('partial', 'Bosch legal-entity metadata is missing.')
    values = [f.get('valueLabel') for f in fields
              if isinstance(f, dict) and f.get('fieldId') == ENTITY_FIELD]
    if len(values) != 1 or not isinstance(values[0], str) or not values[0].strip():
        raise FetchError('partial', 'Bosch legal-entity metadata is missing or ambiguous.')
    return values[0]


def _validate_card(entry):
    if (not isinstance(entry, dict)
            or not isinstance(entry.get('id'), str)
            or not re.fullmatch(r'[0-9]+', entry['id'])
            or not isinstance(entry.get('name'), str) or not entry['name'].strip()
            or entry.get('company', {}).get('identifier') != 'BoschGroup'
            or entry.get('visibility') != 'PUBLIC'
            or entry.get('location', {}).get('country') != 'us'):
        raise FetchError('partial', 'Bosch U.S. listing identity, country or visibility is invalid.')
    return _entity(entry) == ENTITY


def _listing(transport):
    selected = []
    total = None
    seen = set()
    for offset in range(0, boards.MAX_JOBS, 100):
        page = boards.js(transport, API + f'?limit=100&offset={offset}&country=us')
        count = page.get('totalFound')
        entries = page.get('content')
        if (type(count) is not int or not 0 <= count <= boards.MAX_JOBS
                or type(page.get('offset')) is not int or page['offset'] != offset
                or type(page.get('limit')) is not int or page['limit'] != 100
                or not isinstance(entries, list)
                or len(entries) != min(100, count - offset)
                or (total is not None and total != count)):
            raise FetchError('partial', 'Bosch U.S. pagination/count changed or is invalid.')
        total = count
        for entry in entries:
            scoped = _validate_card(entry)
            if entry['id'] in seen:
                raise FetchError('partial', 'Bosch U.S. listing has duplicate posting IDs.')
            seen.add(entry['id'])
            if scoped:
                selected.append(entry)
        if len(seen) == total:
            return selected, total
    raise FetchError('partial', 'Bosch U.S. listing exceeded the inventory limit.')


class _DetailResponse:
    """Replay the already validated response into the shared normalizer."""
    def __init__(self, url, response):
        self.url, self.response = url, response

    def get(self, url):
        if url != self.url:
            raise FetchError('partial', 'Unexpected Bosch detail URL.')
        return self.response


def _posting(transport, entry, company_id, company):
    url = API + '/' + entry['id']
    response = transport.get(url)
    detail = json.loads(boards.checked(response))
    if not _validate_card(detail):
        raise FetchError('partial', 'Bosch detail no longer belongs to U.S. Rexroth.')
    if detail.get('refNumber') != entry.get('refNumber'):
        raise FetchError('partial', 'Bosch listing/detail requisition mismatch.')
    # Some Rexroth legal-notice postings put all duties and requirements in
    # companyDescription. Accept only an explicit employer/title/requisition
    # match with substantive role text, never generic company boilerplate.
    sections = detail['jobAd']['sections']
    description_source = 'jobDescription'
    if not text(sections.get('jobDescription', {}).get('text')):
        body = text(sections.get('companyDescription', {}).get('text'))
        reference = entry.get('refNumber', '')
        title = re.sub(r'\s*\(' + re.escape(reference) + r'\)\s*$', '', entry['name']).strip()
        folded = body.casefold()
        if (not reference or len(body) < 500 or ENTITY.casefold() not in folded
                or reference.casefold() not in folded or title.casefold() not in folded
                or not re.search(r'\b(?:seeks|is seeking)\b', folded)
                or not re.search(r'\b(?:reqs|requirements|qualifications)\b', folded)):
            raise FetchError('partial', 'Bosch full role description is missing or unproven.')
        section = sections.pop('companyDescription')
        sections['jobDescription'] = dict(section, title='Job Description')
        response = HTTPResponse(200, json.dumps(detail).encode())
        description_source = 'companyDescription'
    row = boards.posting(BOARD, _DetailResponse(url, response), entry, company_id, company)
    row['description_source'] = description_source
    if not row['location']:
        raise FetchError('partial', 'Bosch detail location is missing.')
    row.update(legal_entity=ENTITY, employer=ENTITY, country='us',
               req_id=text(detail.get('refNumber')))
    return row


def fetch_bosch_rexroth(url, company_id, company, transport=None, *, progress_factory=None):
    def result(status, jobs, reason):
        return Inventory(status, jobs, reason, SOURCE, 'SmartRecruiters',
                         browser_fallback_allowed=False)

    if (company_id != COMPANY_ID or company.casefold() != COMPANY.casefold()
            or url.rstrip('/') not in SOURCES):
        return result('unsupported', [], 'Bosch Rexroth requires its verified U.S. careers source and exact company identity.')
    transport = transport if transport is not None else boards.Transport(BOARD)
    jobs, completed, revisions = [], {}, []
    reused = fetched = 0
    try:
        progress = progress_factory(SCOPE) if progress_factory is not None else None
        policy = content_digest([boards._detail_policy(company_id, company), Path(__file__).read_bytes(), SCOPE]) if progress else ''
        saved = progress.completed_details(policy) if progress else {}
        entries, us_total = _listing(transport)
        for attempt in range(boards.MAX_INVENTORY_RECONCILIATIONS + 1):
            if attempt == 0:
                completed = {e['id']: saved[e['id']] for e in entries
                             if e['id'] in saved and saved[e['id']][0] == e}
                reused = len(completed)
                jobs = [pair[1] for pair in completed.values()]
            failures = []
            blocked = Event()

            def fetch_entry(entry):
                if blocked.is_set():
                    return entry, None, FetchError('blocked', 'Bosch detail fetching stopped after access denial.')
                try:
                    return entry, _posting(transport, entry, company_id, company), None
                except FetchError as error:
                    if error.status == 'blocked':
                        blocked.set()
                    return entry, None, error
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as error:
                    return entry, None, FetchError('partial', f'Bosch detail validation failed ({type(error).__name__}).')

            pending = [e for e in entries if e['id'] not in completed]
            results = (iter_details(fetch_entry, pending) if type(transport) is boards.Transport
                       else (fetch_entry(e) for e in pending))
            with closing(results):
                for entry, row, error in results:
                    if error:
                        if error.status == 'blocked':
                            raise error
                        failures.append(entry['id'] + ': ' + error.reason)
                    else:
                        completed[entry['id']] = (entry, row)
                        jobs.append(row)
                        fetched += 1
                        if progress:
                            progress.save_detail(entry, row, policy)
            current, us_total = _listing(transport)
            changes = boards._inventory_changes(entries, current)
            if not changes:
                reason = (f'Bosch Rexroth U.S.: verified {len(jobs)} full postings for {ENTITY}; '
                          f'rechecked {us_total} U.S. Bosch listing cards; '
                          f'fetched {fetched} details and reused {reused}.')
                if revisions:
                    reason += ' Reconciled scoped inventory: ' + ' | '.join(revisions) + '.'
                if failures:
                    reason += f' {len(failures)} detail validations failed: ' + '; '.join(failures[:3])
                return result('partial' if failures else 'complete', jobs, reason)
            revisions.append(changes)
            by_id = {entry['id']: entry for entry in current}
            completed = {ident: pair for ident, pair in completed.items() if by_id.get(ident) == pair[0]}
            jobs = [pair[1] for pair in completed.values()]
            entries = current
        raise FetchError('partial', 'Bosch Rexroth scoped inventory kept changing; retry required.')
    except FetchError as error:
        return result('blocked' if error.status == 'blocked' else 'partial', jobs, error.reason)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as error:
        return result('partial', jobs, f'Bosch Rexroth public inventory failed validation ({type(error).__name__}).')

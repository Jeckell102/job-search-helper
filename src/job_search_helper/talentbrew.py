"""Verified public TalentBrew inventories with bounded reconciliation."""
import json
import math
import re
import sys
import time
from urllib.parse import urlsplit
from .ats import Inventory, FetchError, HTTPResponse, _challenge, text
from .shared_boards import Scripts, schema_job

MAX_RECONCILIATIONS = 3
MAX_DETAIL_BYTES = 4 * 1024 * 1024


def employer_key(value):
    return ' '.join(w for w in re.findall('[a-z0-9]+', value.casefold())
                    if w not in {'the', 'inc', 'incorporated', 'company', 'corporation', 'corp'})


def exception_detail(error):
    """Return a bounded, single-line cause suitable for inventory status."""
    message = re.sub(r'\s+', ' ', str(error)).strip()
    if message:
        return f'{type(error).__name__}: {message[:240]}'
    return type(error).__name__


def page_entries(page, root, expected_page, total=None):
    section = page.locator('#search-results[data-total-job-results]')
    if section.count() != 1:
        raise FetchError('partial', 'TalentBrew verified results container missing.')
    attrs = section.evaluate('(e)=>Object.fromEntries(Array.from(e.attributes).map(a=>[a.name,a.value]))')
    if not isinstance(attrs, dict):
        raise FetchError('partial', 'TalentBrew results container returned invalid attributes.')
    counts = {}
    for key in ('data-total-job-results', 'data-records-per-page', 'data-current-page', 'data-total-pages'):
        value = attrs.get(key, '')
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}', value):
            raise FetchError('partial', f'TalentBrew invalid numeric attribute {key}.')
        counts[key] = int(value)
    n, size = counts['data-total-job-results'], counts['data-records-per-page']
    if (not 0 <= n <= 10000 or not 1 <= size <= 100
            or counts['data-current-page'] != expected_page
            or counts['data-total-pages'] != max(1, math.ceil(n / size))
            or (total is not None and total != n)):
        raise FetchError('partial', 'TalentBrew pagination counts changed or are inconsistent.')
    for key in ('data-keywords', 'data-location', 'data-facet-term', 'data-custom-facet-name',
                'data-organization-ids', 'data-refined-keywords', 'data-active-facet-id',
                'data-postal-code', 'data-latitude', 'data-longitude'):
        if attrs.get(key) not in ('', '0', '[]', None):
            raise FetchError('unsupported', f'TalentBrew filtered employer scope requires explicit support ({key}).')
    entries = section.locator('a[data-job-id]').evaluate_all('(els)=>els.map(e=>({id:e.dataset.jobId,url:e.href,title:(e.querySelector("h2")||e).innerText.trim()}))')
    if not isinstance(entries, list):
        raise FetchError('partial', 'TalentBrew listing returned an invalid job-entry collection.')
    for entry in entries:
        if not isinstance(entry, dict):
            raise FetchError('partial', 'TalentBrew listing returned a non-object job entry.')
        if not all(isinstance(entry.get(key), str) for key in ('id', 'url', 'title')):
            raise FetchError('partial', 'TalentBrew listing job entry has invalid id, URL, or title fields.')
        p = urlsplit(entry['url'])
        if (not entry['id'].isdigit() or not entry['title'] or p.scheme != 'https'
                or p.netloc != urlsplit(root).netloc or p.username or p.password
                or p.query or p.fragment or not p.path.endswith('/' + entry['id']) or '/job/' not in p.path):
            raise FetchError('partial', 'TalentBrew job identity invalid.')
    if len(entries) != min(size, max(0, n - (expected_page - 1) * size)):
        raise FetchError('partial', 'TalentBrew result count does not reconcile.')
    return entries, n, size


def next_page(page, number):
    # The results markup can arrive before search.js has attached its delegated
    # click handler. Its exported object is assigned only after those bindings.
    try:
        page.wait_for_function('(n)=>window.elasticSearch && typeof window.elasticSearch.search==="function" && Number(document.querySelector("#search-results")?.getAttribute("data-current-page"))===n-1', arg=number, timeout=30000)
    except Exception as error:
        raise FetchError('partial', f'TalentBrew pagination controller not ready for page {number} ({type(error).__name__}).') from None
    button = page.locator('a.next')
    if button.count() != 1:
        raise FetchError('partial', 'TalentBrew next page missing or ambiguous.')
    try:
        button.click(timeout=30000)
    except Exception as error:
        raise FetchError('partial', f'TalentBrew next-page click failed for page {number} ({type(error).__name__}).') from None
    try:
        page.wait_for_function('(n)=>document.querySelector("#search-results")?.getAttribute("data-current-page")===String(n)', arg=number, timeout=30000)
    except Exception as error:
        raise FetchError('partial', f'TalentBrew results did not advance to page {number} ({type(error).__name__}).') from None


def _access(response):
    if response is None:
        raise FetchError('partial', 'TalentBrew page returned no navigation response.')
    status = getattr(response, 'status', None)
    if not isinstance(status, int):
        raise FetchError('partial', 'TalentBrew HTTP response did not provide a numeric status.')
    if status in (401, 403, 429):
        raise FetchError('blocked', f'TalentBrew HTTP {status}; access denied or rate limited.')
    if status != 200:
        raise FetchError('partial', f'TalentBrew HTTP {status}; posting unavailable, not evidence of closure.')


def _response_html(response, entry):
    """Read one detail response and release it without masking its failure."""
    error = None
    try:
        _access(response)
        response_url = getattr(response, 'url', None)
        if not isinstance(response_url, str) or response_url != entry['url']:
            raise FetchError('partial', 'TalentBrew public detail changed its posting URL.')
        body = response.body()
        if not isinstance(body, bytes):
            raise FetchError('partial', 'TalentBrew public detail returned a non-byte response body.')
        if len(body) > MAX_DETAIL_BYTES:
            raise FetchError('partial', 'TalentBrew detail exceeds the bounded size limit.')
        try:
            return body.decode('utf-8-sig')
        except UnicodeDecodeError as decode_error:
            raise FetchError('partial', f'TalentBrew public detail is not UTF-8 ({exception_detail(decode_error)}).') from decode_error
    except BaseException as caught:
        error = caught
        raise
    finally:
        if response is not None:
            try:
                response.dispose()
            except Exception as dispose_error:
                if error is None:
                    raise FetchError('partial', f'TalentBrew public detail response cleanup failed ({exception_detail(dispose_error)}).') from dispose_error
                if hasattr(error, 'add_note'):
                    error.add_note(f'TalentBrew response cleanup also failed: {exception_detail(dispose_error)}')


def scan(b, context, cid, company, max_jobs=10000, *, progress=None):
    jobs, completed, pages, positions = [], {}, [], {}
    last_detail_request = 0.0
    stage, number, ident, total = 'source scope', 0, '', None
    started = time.monotonic()

    def diagnostic(message):
        return f'TalentBrew {stage}; page={number}; posting={ident or "-"}; advertised={total}; retained={len(jobs)}: {message}'

    def event(kind, **values):
        print(json.dumps(dict(event=kind, provider='TalentBrew', company_id=cid,
                              seconds=round(time.monotonic()-started, 2), **values)), file=sys.stderr)

    try:
        # The configured Boeing division has no verified filter on the parent
        # board. A title keyword is not proof of a business-unit boundary.
        if b.root == 'https://jobs.boeing.com' and employer_key(company) != employer_key('Boeing'):
            raise FetchError('unsupported', 'Boeing parent board does not establish the requested division scope; a verified business-unit feed is required.')
        page = context.new_page(); pages.append(page)
        detail = context.new_page(); pages.append(detail)
        saved = progress._read('talentbrew_detail_v1') if progress is not None else {}
        listing_round = 0

        def snapshot():
            nonlocal stage, number, ident, total, page, listing_round
            if listing_round:
                page.close()
                page = context.new_page(); pages.append(page)
            listing_round += 1
            stage, number, ident = 'listing navigation', 1, ''
            _access(page.goto(b.url, wait_until='domcontentloaded', timeout=30000))
            if urlsplit(page.url).netloc != urlsplit(b.root).netloc:
                raise FetchError('unsupported', 'TalentBrew listing left its verified employer host.')
            page.wait_for_selector('#search-results[data-total-job-results]', state='attached', timeout=30000)
            collected, seen = [], set()
            try:
                stage = 'listing counts'
                entries, total, size = page_entries(page, b.root, 1)
                for number in range(1, max(1, math.ceil(total / size)) + 1):
                    stage = 'listing pagination'
                    if number > 1:
                        next_page(page, number)
                        entries, _, _ = page_entries(page, b.root, number, total)
                    for entry in entries:
                        if entry['id'] in seen:
                            raise FetchError('partial', 'TalentBrew repeated a page or posting.')
                        seen.add(entry['id']); collected.append(entry)
                        positions[entry['id']] = number
                    event('inventory_page', page=number, listed=len(collected), total=total)
                return collected, None
            except FetchError as error:
                if error.status in ('blocked', 'unsupported'):
                    raise
                return collected, diagnostic(error.reason)
            except Exception as error:
                return collected, diagnostic(f'{exception_detail(error)} while validating listing data.')

        entries, listing_error = snapshot()
        for attempt in range(MAX_RECONCILIATIONS + 1):
            failures = []
            for entry in entries:
                ident, stage = entry['id'], 'job detail'
                number = positions[ident]
                cached = completed.get(ident) or saved.get(ident)
                if (isinstance(cached, dict) and not cached.get('retired')
                        and cached.get('source') == b.url and cached.get('entry') == entry
                        and isinstance(cached.get('job'), dict)
                        and cached['job'].get('posting_id') == ident and cached['job'].get('description')
                        and cached['job'].get('company_id') == cid
                        and employer_key(cached['job'].get('company', '')) == employer_key(company)):
                    completed[ident] = cached
                    jobs = [item['job'] for item in completed.values()]
                    continue
                if len(jobs) >= max_jobs:
                    raise FetchError('partial', f'Bounded validation stopped at {len(jobs)} of {total} postings.')
                try:
                    if b.root == 'https://careers.l3harris.com' and hasattr(context, 'request'):
                        # Verified public server-rendered JSON-LD. Read the same
                        # page without loading analytics or application controls.
                        time.sleep(max(0, .4 - (time.monotonic() - last_detail_request)))
                        last_detail_request = time.monotonic()
                        response = context.request.get(entry['url'], timeout=30000, max_redirects=0)
                        content = _response_html(response, entry)
                    else:
                        _access(detail.goto(entry['url'], wait_until='domcontentloaded', timeout=30000))
                        if detail.url.split('?')[0] != entry['url'].split('?')[0]:
                            raise FetchError('partial', 'TalentBrew public detail redirected to a different posting.')
                        detail.wait_for_selector('script[type="application/ld+json"]', state='attached', timeout=10000)
                        content = detail.content()
                    if _challenge(HTTPResponse(200, content.encode('utf-8')), expect_html=True):
                        raise FetchError('blocked', 'TalentBrew public detail requires human verification.')
                    stage = 'job structured data'
                    data = Scripts(content).jobs()
                    if len(data) != 1 or data[0].get('url') != entry['url'] or text(data[0].get('title')) != text(entry['title']):
                        raise FetchError('partial', 'TalentBrew detail identity/title differs from listing.')
                    if employer_key(data[0].get('hiringOrganization', {}).get('name', '')) != employer_key(company):
                        raise FetchError('unsupported', 'TalentBrew employer name does not establish this company scope.')
                    job = schema_job(data[0], entry['url'], ident, 'TalentBrew', cid, company)
                    record = dict(source=b.url, entry=entry, job=job)
                    completed[ident] = record
                    jobs = [item['job'] for item in completed.values()]
                    if progress is not None:
                        progress._write('talentbrew_detail_v1', ident, record)
                except FetchError as error:
                    if error.status in ('blocked', 'unsupported'):
                        raise
                    failures.append((ident, diagnostic(error.reason)))
                except json.JSONDecodeError as error:
                    failures.append((ident, diagnostic(f'Invalid JSON-LD at line {error.lineno}, column {error.colno}: {error.msg}')))
                except Exception as error:
                    failures.append((ident, diagnostic(f'{exception_detail(error)} while reading or validating this posting.')))
                if failures and failures[-1][0] == ident:
                    event('posting_failed', posting_id=ident, attempt=attempt+1, reason=failures[-1][1])
                    if progress is not None:
                        progress._write('talentbrew_error_v1', ident, dict(attempt=attempt+1, reason=failures[-1][1]))
                if len(jobs) and len(jobs) % 100 == 0:
                    event('posting_progress', fetched=len(jobs), total=total)
            if listing_error:
                raise FetchError('partial', listing_error)
            stage, ident = 'full inventory reconciliation', ''
            current, error = snapshot()
            if error:
                raise FetchError('partial', error)
            before, after = ({e['id']: e for e in values} for values in (entries, current))
            if before == after and not failures:
                jobs = [completed[e['id']]['job'] for e in current]
                if progress is not None:
                    for key, record in {**saved, **completed}.items():
                        if key not in after and isinstance(record, dict) and not record.get('retired'):
                            progress._write('talentbrew_detail_v1', key, dict(record, retired=True))
                event('inventory_complete', fetched=len(jobs), rounds=attempt+1)
                return Inventory('complete', jobs, f'TalentBrew: retrieved {len(jobs)} full postings and reconciled all listing pages in {attempt+1} rounds.', b.url, 'TalentBrew')
            event('inventory_reconciliation', round=attempt+1, added=len(after.keys()-before.keys()),
                  removed=len(before.keys()-after.keys()), edited=sum(before[k]!=after[k] for k in before.keys()&after.keys()), unresolved=len(failures))
            if attempt == MAX_RECONCILIATIONS:
                raise FetchError('partial', 'Bounded full-list reconciliation exhausted. ' + '; '.join(reason for _, reason in failures[:3]))
            entries = current
    except FetchError as error:
        return Inventory(error.status, jobs, diagnostic(error.reason), b.url, 'TalentBrew')
    except Exception as error:
        return Inventory('partial', jobs, diagnostic(f'{exception_detail(error)} while reading or validating public data.'), b.url, 'TalentBrew')
    finally:
        for page in pages:
            try:page.close()
            except Exception:pass

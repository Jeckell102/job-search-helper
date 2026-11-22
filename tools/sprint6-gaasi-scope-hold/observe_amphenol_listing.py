"""One bounded listing-only observation with the installed Amphenol adapter."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import monotonic
from urllib.parse import urlsplit

PROJECT = Path('/home/chris/job-search-helper_old')
JOURNAL = PROJECT / '.state/integration-release-journal.json'
JOURNAL_PIN = '22da0b905498584bd4327289f12be912d962bff8d1c18281e467b037247f6c6f'
ADAPTER = PROJECT / 'src/job_search_helper/acquiretm.py'
ADAPTER_PIN = 'ac1b1e62ca139fcef47cae368ac25ebc56043a6d3133428ec2e97f22fdbc9e7c'


def verify():
    if sha256(JOURNAL.read_bytes()).hexdigest() != JOURNAL_PIN or sha256(ADAPTER.read_bytes()).hexdigest() != ADAPTER_PIN:
        raise ValueError('The active installed observation pins changed.')


verify()
sys.path.insert(0, str(PROJECT / 'src'))
from job_search_helper import acquiretm
from job_search_helper.ats import FetchError
from playwright.sync_api import sync_playwright

if Path(acquiretm.__file__) != ADAPTER:
    raise ValueError('The listing observation did not load the measured adapter.')
start = monotonic()
status_codes = set()
result = {'company_id': 'COMP-0490', 'source': acquiretm.SOURCE, 'adapter_sha256': ADAPTER_PIN,
          'installed_journal_sha256': JOURNAL_PIN, 'scope': 'one_public_listing_traversal',
          'details_requested': False, 'production_changes': False}


def observe_response(response):
    if urlsplit(response.url).hostname == acquiretm.HOST and response.status >= 400:
        status_codes.add(response.status)


with sync_playwright() as playwright:
    with playwright.chromium.launch(headless=True) as browser:
        context = browser.new_context()
        context.route('**/job_details_clean.aspx*', lambda route: route.abort())
        page = context.new_page()
        page.on('response', observe_response)
        try:
            entries = acquiretm.inventory(page, diagnose_pagination=True)
            result.update(state='LISTING_COMPLETE', listing_count=len(entries),
                          distinct_listing_ids_sha256=acquiretm._ids_digest(entries))
        except FetchError as error:
            result.update(state='LISTING_HELD', provider_status=error.status,
                          typed_failure=error.outcome_failure)
verify()
result.update(measured_at=datetime.now(timezone.utc).isoformat(), duration_seconds=round(monotonic()-start, 3),
              selected_host_error_statuses=sorted(status_codes))
if status_codes & {403, 429}:
    result['state'] = 'LISTING_ACCESS_HELD'
print(json.dumps(result, sort_keys=True))

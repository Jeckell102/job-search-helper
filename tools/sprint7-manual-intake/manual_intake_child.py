"""Prevent all real transport and keep the admitted manual scope visible."""
import json
import os
from pathlib import Path
import sys


def audit(event, _args):
    if event.startswith(('socket.', 'subprocess.')):
        raise AssertionError('The private manual intake canary refuses external transport.')


sys.addaudithook(audit)
if 'JSH_SCRAPER_RUNTIME_BINDING' in os.environ:
    from job_search_helper import ats, cli
    from job_search_helper.repository import GoogleRepository
    from job_search_helper.sheet_profile import COMPACT_SCHEMAS
    from sheets_fixture import RangeSheets

    root = Path.cwd()
    expected = json.loads((root / 'private-company-fixture.json').read_bytes())
    def broad(*_args, **_kwargs):
        raise AssertionError('The selected new Company must not enter the broad workflow.')

    def provider(label, url, company_id, company_name):
        assert (label, url, company_id, company_name) == (
            expected['ATS / Source'], expected['Official Careers URL'], expected['Company ID'], expected['Company'])
        with (root / '.state/provider-once').open('x') as marker:
            marker.write(company_id)
        return ats.Inventory('complete', source_url=url, ats=label, verified_zero='greenhouse_explicit_total_zero')

    def workbook(*, write, **_kwargs):
        assert not write
        with (root / '.state/workbook-read').open('a') as trace:
            trace.write('READ_ONLY\n')
        return GoogleRepository(RangeSheets({'Companies': [expected]}, schemas=COMPACT_SCHEMAS),
                                os.environ['SPREADSHEET_ID'], schemas=COMPACT_SCHEMAS, min_request_interval=0)

    ats.fetch_inventory = provider
    cli.get_remote_repository = workbook
    from job_search_helper import scrape_first_pass
    scrape_first_pass.main = broad

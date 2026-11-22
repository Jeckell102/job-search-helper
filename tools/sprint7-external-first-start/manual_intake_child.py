"""Prevent all real transport and keep the admitted manual scope visible."""
import atexit
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
    scenario = (root / 'scenario').read_text()
    expected = json.loads((root / 'private-company-fixture.json').read_bytes())
    def broad(*_args, **_kwargs):
        if scenario == 'no_addition':
            assert os.fstat(int(os.environ['JSH_SCRAPER_ADMISSION_FD'])).st_ino == (root/'.state/scraper.lock').stat().st_ino
            print('PRESERVED_NORMAL_START')
            return 0
        raise AssertionError('The selected new Company must not enter the broad workflow.')

    def provider(label, url, company_id, company_name):
        assert (label, url, company_id, company_name) == (
            expected['ATS / Source'], expected['Official Careers URL'], expected['Company ID'], expected['Company'])
        with (root / '.state/provider-once').open('x') as marker:
            marker.write(company_id)
        if scenario == 'sheets_only_jobs':
            job = {'title': 'Implementation Manager', 'posting_id': 'manual-intake-42',
                   'location': 'Remote, United States', 'url': url + '/jobs/42', 'ats': label,
                   'description': 'Coordinate deployment and customer implementation. ' +
                                  'Work with customers on production rollout and testing. ' * 130}
            return ats.Inventory('complete', [job], source_url=url, ats=label)
        return ats.Inventory('complete', source_url=url, ats=label, verified_zero='greenhouse_explicit_total_zero')

    def workbook(*, write, interactive, **_kwargs):
        assert not write or scenario == 'sheets_only_jobs'
        trace_path = root / '.state/workbook-read'
        first = not trace_path.exists()
        assert interactive is (first and scenario not in {'idle', 'busy_then_idle'})
        with trace_path.open('a') as trace:
            trace.write('WRITE_FIXTURE\n' if write else 'READ_ONLY\n')
        rows = [expected]
        if scenario == 'multiple':
            rows.append({**expected, 'Company ID': 'COMP-9003', 'Company': 'Another external Company'})
        elif scenario == 'stale_external' and not first:
            rows = [{**expected, 'Last Checked': 'Changed in Sheets during selection'}]
        elif scenario == 'duplicate_name':
            rows.append({**expected, 'Company ID': 'COMP-9001', 'Company': expected['Company'].upper()})
        elif scenario == 'blank_status':
            rows = [{**expected, 'Company Status': ''}]
        elif scenario == 'missing_id':
            rows = [{**expected, 'Company ID': ''}]
        service = RangeSheets({'Companies': rows}, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(service, os.environ['SPREADSHEET_ID'],
                                  schemas=COMPACT_SCHEMAS, min_request_interval=0)
        if write:
            @atexit.register
            def retain_publication():
                result = {'job_keys': [row['Job Key'] for row in remote.read('Job History')],
                          'batches': len(service.batches)}
                (root / '.state/fixture-publication.json').write_text(json.dumps(result))
        return remote

    ats.fetch_inventory = provider
    cli.get_remote_repository = workbook
    from job_search_helper import scrape_first_pass
    scrape_first_pass.main = broad

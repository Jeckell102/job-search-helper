"""Measured scratch-only dependency for the separate canary child."""
import atexit
from hashlib import sha256
import json
import os
from pathlib import Path
import sys


def audit(event, args):
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.exec', 'os.posix_spawn', 'os.system'}:
        raise AssertionError('The canary child forbids sockets and child processes.')


sys.addaudithook(audit)


def setup():
    root = Path.cwd().resolve()
    assert root.name == 'project' and root.is_relative_to('/tmp')
    paths = root / '.state'
    runtime = json.loads(os.environ['JSH_SCRAPER_RUNTIME_BINDING'])
    project_src = root / 'src'
    sys.path[:0] = [str(project_src), str(root / 'tests')]
    from job_search_helper import ats

    def captured_inventory(provider, url, company_id, name):
        assert (provider, url, company_id, name) == (
            'AcquireTM', 'https://amphenol-aerospace.acquiretm.com/home.aspx',
            'COMP-0490', 'Amphenol Aerospace',
        )
        payload = (root / 'public-inventory.private.json').read_bytes()
        assert sha256(payload).hexdigest() == '94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8'
        saved = json.loads(payload)
        assert saved['inventory_status'] == 'complete' and len(saved['jobs']) == 39
        with (paths / 'captured-fetch-once').open('x') as marker:
            marker.write(runtime['release_id'] + '\n')
        return ats.Inventory('complete', saved['jobs'], saved['reason'], url, provider)

    # Engine binds its default fetcher when imported. Set the fixture input
    # first. Neither the Engine nor the planner/publisher is substituted.
    assert 'job_search_helper.engine' not in sys.modules
    ats.fetch_inventory = captured_inventory
    from job_search_helper import cli
    from job_search_helper.repository import GoogleRepository
    from job_search_helper.sheet_profile import COMPACT_SCHEMAS
    from sheets_fixture import RangeSheets

    def workbook(**kwargs):
        assert kwargs == {'write': True, 'schemas': COMPACT_SCHEMAS, 'evidence_archives': False}
        assert os.environ.get('SPREADSHEET_ID') == 'sheet'
        with (paths / 'workbook-open-once').open('x') as marker:
            marker.write(runtime['release_id'] + '\n')
        rows = json.loads((root / 'workbook-before.private.json').read_text())
        fixture = RangeSheets(rows, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(fixture, 'sheet', schemas=COMPACT_SCHEMAS, min_request_interval=0)

        @atexit.register
        def retain_workbook():
            evidence = {'jobs': remote.read('Job History'), 'companies': remote.read('Companies'),
                        'batches': len(fixture.batches)}
            (paths / 'workbook-after.private.json').write_text(json.dumps(evidence, sort_keys=True) + '\n')
        return remote

    cli.get_remote_repository = workbook
    with (paths / 'measured-child.jsonl').open('a') as output:
        output.write(json.dumps({'pid': os.getpid(), 'runtime': runtime}, sort_keys=True) + '\n')


if 'JSH_SCRAPER_RUNTIME_BINDING' in os.environ:
    setup()

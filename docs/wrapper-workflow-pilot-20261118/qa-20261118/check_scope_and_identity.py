"""QA-only reproductions using temporary stores and source fixtures.

Imports the installed coordinator. Never instantiates a production Store,
starts a scheduler, calls a model, or runs any production scraper.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, '/home/chris/job-search-helper_old/dev/wrapper-coder/tools')
import coordinator as c
from test_coordinator import CoordinatorTests


def check_scope():
    fixture = CoordinatorTests()
    fixture.setUp()
    try:
        other = fixture.root / 'src/unassigned_company.py'
        other.write_text('employer = "unrelated"\n')
        task = fixture.task('Repair src/a.py and run tests/test_a.py', mode='develop')
        state = fixture.co.store.update(task, phase='implement', status='RUNNING', manifest=c.manifest())
        args = {'path': 'src/unassigned_company.py', 'sha256': hashlib.sha256(other.read_bytes()).hexdigest(),
                'old': '"unrelated"', 'new': '"overwritten"'}
        result = fixture.co.execute(state, 'code_edit', args, {'code_edit'})
        print(json.dumps({'check': 'unassigned_company_edit', 'allowed': result.get('ok'),
                          'changed': 'overwritten' in other.read_text(),
                          'assigned': state['evidence_requirements']['required_files']}))
        test = fixture.root / 'tests/test_a.py'
        args = {'path': 'tests/test_a.py', 'sha256': hashlib.sha256(test.read_bytes()).hexdigest(),
                'old': test.read_text(), 'new': 'def test_a(): pass\n'}
        result = fixture.co.execute(fixture.co.store.get(task), 'code_edit', args, {'code_edit'})
        print(json.dumps({'check': 'acceptance_assertion_removal', 'allowed': result.get('ok'),
                          'after': test.read_text().strip()}))
    finally:
        fixture.doCleanups()


def check_identity():
    fixture = CoordinatorTests()
    fixture.setUp()
    try:
        objective = ('Repair COMP-0001 Alpha in src/a.py using https://alpha.example/careers. '
                     'Run tests/test_a.py.')
        metadata = {'company_id': 'COMP-0002', 'company': 'Beta',
                    'configured_url': 'https://beta.example/jobs',
                    'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py']}
        result = fixture.co.command({'action': 'batch', 'items': [
            {'objective': objective, 'mode': 'develop', 'integration': metadata}]})
        state = fixture.co.store.get(result['ids'][0])
        packet = json.loads(fixture.co.messages(state, 'Protocol')[1]['content'])
        print(json.dumps({'check': 'mismatched_structured_identity', 'accepted': result['ok'],
                          'stored_company': state['integration']['company'],
                          'worker_objective': packet['objective'],
                          'structured_identity_in_packet': 'integration' in packet}))
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    check_scope()
    check_identity()

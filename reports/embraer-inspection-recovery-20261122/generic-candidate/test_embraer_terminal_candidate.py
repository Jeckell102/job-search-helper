import sys
import types
import hashlib
import json

from embraer_terminal_candidate import derive_embraer_final_diff, read_embraer_terminal_candidate
from coordinator_store import Store as InstalledStore


MANIFEST = {'src/job_search_helper/shared_boards.py': 'a' * 64}


class Enrollment:
    request_id = 'operator-embraer-20261122-01'
    source_revision = 'b' * 64
    baseline_sha256 = 'c' * 64

    def _sources_match(self, project): return project == '/workspace'
    def _source(self, jobs, destination):
        return {'record': {'outcome_id': 'OUT-' + 'd' * 24}, 'company': {'company_id': 'COMP-0634'}}
    def _paired(self, store, source, *, exact_repair_key=None):
        self.paired_key = exact_repair_key
        return store.held, store.task
    def _proposal(self, held, company): return {'integration': {'work_order': 'breezy-embraer-brand-heading-v1'}}
    def _task_matches(self, held, task, proposal): return held == {'repair_key': 'r'}


class Store:
    def __init__(self, status='AWAITING_LIVE_VALIDATION'):
        self.held = {'repair_key': 'r'}
        self.task = {'id': 'WRAP-fbb9ff24d3', 'status': status, 'phase': 'verify',
                     'integration': {'work_order': 'breezy-embraer-brand-heading-v1'},
                     'edit_scope': {'paths': ['src/job_search_helper/shared_boards.py'], 'digest': 'scope', 'version': 1}}
    def unresolved_inferences(self): return []
    def receipts(self, task_id):
        good = {'ok': True, 'result': {'exit_code': 0, 'independent_acceptance': True}}
        return [
            {'phase': 'verify', 'name': 'code_test', 'result': good, 'source_unchanged_during_test': True},
            {'phase': 'verify', 'name': 'acceptance_test', 'result': good},
            {'phase': 'verify', 'name': 'code_diff', 'result': {'ok': True},
             'source_unchanged_during_diff': True,
             'source_manifest_sha256': 'a6' * 32},
        ]


def _acceptance(monkeypatch):
    module = types.SimpleNamespace(validate_scope=lambda task: task['edit_scope'],
                                   validate_bundle=lambda store, task: {'digest': 'bundle'},
                                   digest=lambda value: 'acceptance-' + hashlib.sha256(
                                       json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
    monkeypatch.setitem(sys.modules, 'coordinator_acceptance', module)
    monkeypatch.setitem(sys.modules, 'coordinator_evidence', types.SimpleNamespace(
        manifest_digest=lambda value: 'manifest-' + hashlib.sha256(
            json.dumps(value, sort_keys=True).encode()).hexdigest()))


def _receipt(identifier, name, result):
    """Match the ordinary Store.receipts mapping, which deliberately has no status."""
    return {'id': identifier, 'task': 'WRAP-fbb9ff24d3', 'phase': 'verify', 'name': name,
            'arguments': {}, 'signature': 'sig-' + str(identifier), 'created': float(identifier), 'result': result}


def test_exact_terminal_binding(monkeypatch):
    _acceptance(monkeypatch)
    source_digest = sys.modules['coordinator_evidence'].manifest_digest(MANIFEST)
    acceptance_digest = sys.modules['coordinator_acceptance'].digest(MANIFEST)
    store = Store()
    store.receipts = lambda _id: [
        _receipt(1, 'code_test', {'ok': True, 'result': {'exit_code': 0},
         'source_unchanged_during_test': True}),
        _receipt(2, 'acceptance_test', {'ok': True, 'result': {
            'exit_code': 0, 'independent_acceptance': True, 'acceptance_bundle_digest': 'bundle',
            'edit_scope_digest': 'scope', 'edit_scope_version': 1,
            'source_manifest_digest': acceptance_digest}}),
        _receipt(3, 'code_diff', {'ok': True,
         'source_unchanged_during_diff': True, 'source_manifest_sha256': source_digest}),
    ]
    enrollment = Enrollment()
    result = read_embraer_terminal_candidate(enrollment, store, project='/workspace', jobs='jobs', destination='sheet',
                                              current_source_manifest=MANIFEST,
                                              current_acceptance_source_manifest=MANIFEST,
                                              final_diff={'paths': ['src/job_search_helper/shared_boards.py'], 'source_manifest': MANIFEST},
                                              expected_task_id='WRAP-fbb9ff24d3')
    assert result and result['task_id'] == 'WRAP-fbb9ff24d3'
    enrollment.successor = types.SimpleNamespace(predecessor_repair_key='e' * 64)
    successor = read_embraer_terminal_candidate(enrollment, store, project='/workspace', jobs='jobs', destination='sheet',
                                                 current_source_manifest=MANIFEST,
                                                 current_acceptance_source_manifest=MANIFEST,
                                                 final_diff={'paths': ['src/job_search_helper/shared_boards.py'], 'source_manifest': MANIFEST},
                                                 expected_task_id='WRAP-fbb9ff24d3')
    assert successor and enrollment.paired_key == InstalledStore._operator_successor_repair_key('e' * 64)


def test_nonterminal_or_out_of_scope_candidate_holds(monkeypatch):
    _acceptance(monkeypatch)
    assert read_embraer_terminal_candidate(Enrollment(), Store('RUNNING'), project='/workspace', jobs='jobs', destination='sheet',
                                            current_source_manifest=MANIFEST,
                                            current_acceptance_source_manifest=MANIFEST,
                                            final_diff={'paths': ['src/job_search_helper/shared_boards.py'], 'source_manifest': MANIFEST},
                                            expected_task_id='WRAP-fbb9ff24d3') is None
    assert read_embraer_terminal_candidate(Enrollment(), Store(), project='/workspace', jobs='jobs', destination='sheet',
                                            current_source_manifest=MANIFEST,
                                            current_acceptance_source_manifest=MANIFEST,
                                            final_diff={'paths': ['src/other.py'], 'source_manifest': MANIFEST},
                                            expected_task_id='WRAP-fbb9ff24d3') is None


def test_unsettled_ordinary_tool_row_holds_without_invented_status(monkeypatch):
    _acceptance(monkeypatch)
    store = Store()
    store.receipts = lambda _id: [_receipt(1, 'code_read', None)]
    assert read_embraer_terminal_candidate(Enrollment(), store, project='/workspace', jobs='jobs', destination='sheet',
                                            current_source_manifest=MANIFEST,
                                            current_acceptance_source_manifest=MANIFEST,
                                            final_diff={'paths': ['src/job_search_helper/shared_boards.py'],
                                                        'source_manifest': MANIFEST},
                                            expected_task_id='WRAP-fbb9ff24d3') is None


def test_derives_only_scoped_changed_source_from_physical_pilot_baseline(tmp_path):
    from coordinator_baseline import binding, files

    baseline = tmp_path / 'pilot-base'
    workspace = tmp_path / 'tasks' / 'WRAP-fbb9ff24d3' / 'repo'
    for root in (baseline, workspace):
        (root / 'src/job_search_helper').mkdir(parents=True)
        (root / 'tests').mkdir()
        (root / 'src/job_search_helper/shared_boards.py').write_text('before = 1\n')
        (root / 'src/job_search_helper/off_scope.py').write_text('stable = 1\n')
        (root / 'tests/test_embraer_typed_defect.py').write_text('assert True\n')
    (workspace / 'src/job_search_helper/shared_boards.py').write_text('after = 2\n')
    task = {'id': 'WRAP-fbb9ff24d3', 'assignment_baseline': binding(files(baseline)),
            'edit_scope': {'paths': ['src/job_search_helper/shared_boards.py', 'tests/test_embraer_typed_defect.py']},
            'integration_identity': {'source_targets': ['src/job_search_helper/shared_boards.py']},
            'manifest': files(workspace)}
    projection = derive_embraer_final_diff(task, types.SimpleNamespace(base=tmp_path / 'tasks'), pilot_baseline=baseline,
                                            expected_task_id='WRAP-fbb9ff24d3')
    assert projection['paths'] == ['src/job_search_helper/shared_boards.py']
    assert projection['before'] != projection['after']
    (workspace / 'src/job_search_helper/off_scope.py').write_text('drift = 1\n')
    assert derive_embraer_final_diff(task, types.SimpleNamespace(base=tmp_path / 'tasks'), pilot_baseline=baseline,
                                     expected_task_id='WRAP-fbb9ff24d3') is None
    (workspace / 'src/job_search_helper/off_scope.py').write_text('stable = 1\n')
    assert derive_embraer_final_diff(task, types.SimpleNamespace(base=tmp_path / 'tasks'), pilot_baseline=baseline,
                                     expected_task_id='WRAP-fbb9ff24d3')['paths'] == [
        'src/job_search_helper/shared_boards.py']
    (workspace / 'src/job_search_helper/shared_boards.py').unlink()
    assert derive_embraer_final_diff(task, types.SimpleNamespace(base=tmp_path / 'tasks'), pilot_baseline=baseline,
                                     expected_task_id='WRAP-fbb9ff24d3') is None

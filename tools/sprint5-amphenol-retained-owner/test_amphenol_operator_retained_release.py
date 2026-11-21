from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest


def _module():
    import amphenol_operator_retained_release as release
    return release


def _fixture(tmp_path):
    release = _module()
    root = tmp_path / 'state'; root.mkdir()
    for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'):
        with sqlite3.connect(root / name):
            pass
    project = tmp_path / 'project'; project.mkdir()
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    manifest = {'release_id': 'REL-' + 'a' * 24, 'company_id': 'COMP-0490',
                'failed_request_id': 'operator-request', 'source_revision': 'b' * 64,
                'files': {'src/job_search_helper/acquiretm.py': {'before': {'sha256': 'c' * 64},
                                                                  'after': {'sha256': 'd' * 64}}}}
    source = {'record': {'identity': {'request_id': 'operator-request'}}, 'stale': False,
              'acknowledged': True}
    prepared = {'binding': {'outcome_id': 'OUT-' + 'a' * 24, 'request_id': 'operator-request'},
                'messages': ['prompt'], 'tools': ['tool']}
    receipt = {'task': 'WRAP-1234567890', 'phase': 'inspect', 'status': 'COMPLETED',
               'accepted_recipe_choice': {'summary': 'W1', 'next_action': 'listing_membership_change', 'outcome': 'phase_done'},
               'request_id': 'req', 'control_binding': {'schema': 'inference-control-binding-v1'},
               'prompt_digest': 'prompt', 'tools_digest': 'tools', 'response_digest': 'response'}
    task = {'id': 'WRAP-1234567890', 'status': 'PAUSED_ERROR', 'isolated_workspace': True,
            'held_repair_key': 'repair-key',
            'repair_provenance': {'repair_key': 'repair-key', 'outcome_id': 'OUT-' + 'a' * 24,
                                  'company_id': 'COMP-0490', 'source_revision': 'b' * 64},
            'integration': {'work_order': 'acquiretm-listing-membership-v1'}}
    store_path = tmp_path / 'tasks.sqlite3'
    with sqlite3.connect(store_path) as db:
        db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL)')
        db.execute('CREATE TABLE inference_receipts(request_id TEXT PRIMARY KEY, task TEXT NOT NULL, '
                   'status TEXT NOT NULL, data TEXT NOT NULL)')
        db.execute('INSERT INTO tasks VALUES (?,?)', (task['id'], json.dumps(task)))
        db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                   (receipt['request_id'], task['id'], receipt['status'], json.dumps(receipt)))
    store = SimpleNamespace(path=store_path)
    return release, dict(project_root=project, root=root, store=store, outcome_id='OUT-' + 'a' * 24,
                         request_sha256='e' * 64, source_revision='b' * 64,
                         historical_task_id='WRAP-1234567890', candidate_root=candidate,
                         manifest=manifest, approval_path='/owner', approval_fd=7,
                         owner_identity=(1, 2), approval_sha256='f' * 64), source, prepared


def test_operator_preflight_holds_without_independent_owner(monkeypatch, tmp_path):
    release, kwargs, source, prepared = _fixture(tmp_path)
    monkeypatch.setattr(release, 'canonical_manifest', lambda value: value)
    monkeypatch.setattr(release, '_candidate_matches', lambda *args: True)
    monkeypatch.setattr(release, 'digest', lambda value: 'prompt' if value == ['prompt'] else 'tools')
    monkeypatch.setattr(release, 'valid_inference_binding', lambda *args: True)
    import amphenol_recipe_choice_input as choice
    monkeypatch.setattr(choice, 'read_operator_owned_source', lambda *args, **items: source)
    monkeypatch.setattr(choice, 'read_operator_owned_choice_input', lambda *args, **items: prepared)
    @contextmanager
    def rejected(*args, **items):
        raise ValueError('untrusted self-labelled pass')
        yield
    monkeypatch.setattr(release, 'open_release_qualification_owner', rejected)
    assert release.continue_operator_retained_release(
        execute=False, current_source_revision=lambda _: None, dependency_digest=lambda: None,
        verify=lambda *_: None, **kwargs) == {'state': 'HELD_OPERATOR_RETAINED_QUALIFICATION'}


def test_exact_operator_preflight_delegates_only_on_explicit_execution(monkeypatch, tmp_path):
    release, kwargs, source, prepared = _fixture(tmp_path)
    monkeypatch.setattr(release, 'canonical_manifest', lambda value: value)
    monkeypatch.setattr(release, '_candidate_matches', lambda *args: True)
    monkeypatch.setattr(release, 'digest', lambda value: 'prompt' if value == ['prompt'] else 'tools')
    monkeypatch.setattr(release, 'valid_inference_binding', lambda *args: True)
    import amphenol_recipe_choice_input as choice
    monkeypatch.setattr(choice, 'read_operator_owned_source', lambda *args, **items: source)
    monkeypatch.setattr(choice, 'read_operator_owned_choice_input', lambda *args, **items: prepared)
    class Owner:
        def require(self, manifest):
            assert manifest is kwargs['manifest']
    @contextmanager
    def owner(*args, **items):
        yield Owner()
    monkeypatch.setattr(release, 'open_release_qualification_owner', owner)
    held = release.continue_operator_retained_release(
        execute=False, current_source_revision=lambda _: None, dependency_digest=lambda: None,
        verify=lambda *_: None, **kwargs)
    assert held == {'state': 'HELD_OPERATOR_RETAINED_RELEASE_PREFLIGHT', 'release_id': 'REL-' + 'a' * 24}
    calls = []
    monkeypatch.setattr(release, 'release_and_continue_qualified',
                        lambda *args, **items: calls.append((args, items)) or {'state': 'REQUEST_WRITTEN'})
    result = release.continue_operator_retained_release(
        execute=True, current_source_revision=lambda company: 'b' * 64, dependency_digest=lambda: 'd' * 64,
        verify=lambda *_: {'result': 'PASS'}, **kwargs)
    assert result == {'state': 'REQUEST_WRITTEN'}
    args, items = calls[0]
    assert args[:2] == (kwargs['project_root'], kwargs['candidate_root'])
    assert args[4] is kwargs['manifest']
    assert items['approval_path'] == '/owner'


@pytest.mark.parametrize('field', ('project_root', 'candidate_root', 'root'))
def test_operator_preflight_rejects_ancestor_symlink_alias(monkeypatch, tmp_path, field):
    release, kwargs, source, prepared = _fixture(tmp_path)
    monkeypatch.setattr(release, 'canonical_manifest', lambda value: value)
    monkeypatch.setattr(release, '_candidate_matches', lambda *args: True)
    monkeypatch.setattr(release, 'digest', lambda value: 'prompt' if value == ['prompt'] else 'tools')
    monkeypatch.setattr(release, 'valid_inference_binding', lambda *args: True)
    import amphenol_recipe_choice_input as choice
    monkeypatch.setattr(choice, 'read_operator_owned_source', lambda *args, **items: source)
    monkeypatch.setattr(choice, 'read_operator_owned_choice_input', lambda *args, **items: prepared)
    @contextmanager
    def owner(*args, **items):
        yield SimpleNamespace(require=lambda manifest: None)
    monkeypatch.setattr(release, 'open_release_qualification_owner', owner)
    physical = tmp_path / 'physical'; physical.mkdir()
    target = kwargs[field]
    moved = physical / target.name
    target.rename(moved)
    alias = tmp_path / 'alias'; alias.symlink_to(physical, target_is_directory=True)
    assert release.preflight_operator_retained_release(**{**kwargs, field: alias / target.name}) is None


def test_operator_preflight_holds_when_store_database_disappeared(tmp_path):
    release, kwargs, _, _ = _fixture(tmp_path)
    missing_store = SimpleNamespace(path=tmp_path / 'missing-store.sqlite3')
    assert release.preflight_operator_retained_release(**{**kwargs, 'store': missing_store}) is None
    assert not missing_store.path.exists()

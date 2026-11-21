import sys

from job_search_helper import cli
from test_manual_company_start import add_company, manual


LOCAL_FACTORY = cli.get_repository


def test_selector_never_opens_remote_before_validating_admission(manual, monkeypatch):
    root, repository, launch = manual
    event = add_company(repository, 1)
    assert event['kind'] == 'company.eligible'
    marker = root.parent / '.storage-backend'
    marker.write_text('sqlite')
    monkeypatch.delenv('JOB_STORAGE_BACKEND')
    monkeypatch.setattr(cli, 'PROJECT_ROOT', root.parent)
    monkeypatch.setattr(cli, 'get_repository', LOCAL_FACTORY)
    calls = []

    def remote(**_):
        calls.append('remote factory')
        raise ValueError('fixture intercepted the attempted remote factory')

    monkeypatch.setattr(cli, 'get_remote_repository', remote)
    runner = sys.modules['job_search_helper.manual_candidate_runner']
    monkeypatch.setattr(runner, '_load_environment', lambda: marker.write_text('sheets'))
    assert launch() == 1
    print(f'remote callbacks={calls}; queue created={(root / "next-scan.json").exists()}')
    assert not (root / 'next-scan.json').exists()
    assert not calls

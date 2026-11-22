"""One composed fixture for source-only installation and interrupted rollback."""

from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2, copytree, ignore_patterns
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parent
LIVE = Path('/home/chris/job-search-helper_old')
sys.path[:0] = [str(SOURCE), str(LIVE), str(LIVE / 'src')]
from release_admission_bootstrap import _validate_runtime
import native_source_advance as advance


RUN_BOOTSTRAP = '''
import importlib.util
import json
from pathlib import Path
import sys
project = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('checked_bootstrap', sys.argv[2])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module._validate_runtime(project, project / '.state'), sort_keys=True))
'''


def check_fresh_bootstrap(project, bootstrap, expected):
    result = subprocess.run([sys.executable, '-I', '-B', '-c', RUN_BOOTSTRAP,
                             str(project), str(bootstrap)], text=True, capture_output=True, check=False)
    if expected is None:
        assert result.returncode != 0 and 'Interrupted integration release' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected


def fixture(directory):
    project = directory / 'project'
    project.mkdir()
    copytree(LIVE / 'src', project / 'src', ignore=ignore_patterns('__pycache__', '*.pyc'))
    copy2(SOURCE / 'before/release_admission_bootstrap.py', project / 'release_admission_bootstrap.py')
    copy2(LIVE / 'pyproject.toml', project / 'pyproject.toml')
    root = project / '.state'
    root.mkdir(mode=0o700)
    files = _validate_runtime(project, root)
    old_release = 'REL-' + 'a' * 24
    binding = {'schema': 'integration-release-binding-v1', 'release_id': old_release,
               **{key: files[key] for key in advance.RUNTIME_FIELDS}}
    old_record = root / 'fixture-prior-release'
    old_record.mkdir()
    receipt = old_record / 'receipt.json'
    receipt.write_text(json.dumps({'state': 'COMPLETE', 'release_id': old_release,
                                   'manifest_sha256': 'b' * 64, 'release': binding}))
    journal = root / 'integration-release-journal.json'
    journal.write_text(json.dumps({'schema': 'integration-release-journal-v1', 'state': 'COMPLETE',
                                   'record': str(old_record), 'release_id': old_release,
                                   'manifest_sha256': 'b' * 64, 'release': binding}))
    predecessor = _validate_runtime(project, root)
    package = directory / 'package'
    package.mkdir(mode=0o700)
    for side in ('before', 'staged'):
        copytree(SOURCE / side, package / side)
    spec = json.loads((SOURCE / 'PREPARED_PACKAGE.json').read_bytes())
    spec['live_runtime'] = predecessor
    spec['live_journal_sha256'] = sha256(journal.read_bytes()).hexdigest()
    raw = json.dumps(spec, sort_keys=True).encode()
    (package / 'PREPARED_PACKAGE.json').write_bytes(raw)
    return project, package, sha256(raw).hexdigest(), journal, predecessor, receipt


def test_single_reversible_source_advance():
    with TemporaryDirectory(prefix='jsh-s6-native-install-fixture-') as directory:
        root = Path(directory)
        before_dir, failing_dir = root / 'install', root / 'interruption'
        before_dir.mkdir()
        failing_dir.mkdir()
        project, package, pin, journal, predecessor, old_receipt = fixture(before_dir)
        historical = old_receipt.read_bytes()
        old_adapter = (project / 'src/job_search_helper/acquiretm.py').read_bytes()
        original_journal = journal.read_bytes()
        write_json = advance.release._write_json

        def cut_before_prepared(path, value):
            if path == journal and value.get('state') == 'PREPARED':
                raise OSError('fixture cut before PREPARED')
            return write_json(path, value)

        with patch.object(advance.release, '_write_json', cut_before_prepared):
            try:
                advance.advance(project, package, pin)
            except OSError as error:
                assert str(error) == 'fixture cut before PREPARED'
            else:
                raise AssertionError('The fixture did not interrupt preparation.')
        assert journal.read_bytes() == original_journal
        assert len(list((journal.parent / 'native-runtime-releases').iterdir())) == 1
        check_fresh_bootstrap(project, project / 'release_admission_bootstrap.py', predecessor)
        result = advance.advance(project, package, pin)
        assert result['schema'] == 'native-source-maintenance-receipt-v1'
        assert 'failed_request_id' not in result and 'company_id' not in result
        expected = {'state': 'COMPLETE', **{key: result['release'][key]
                    for key in ('release_id', *advance.RUNTIME_FIELDS)}}
        check_fresh_bootstrap(project, project / 'release_admission_bootstrap.py', expected)
        assert old_receipt.read_bytes() == historical
        assert (project / 'src/job_search_helper/acquiretm.py').read_bytes() == old_adapter
        assert not (journal.parent / 'next-scan.json').exists()

        project, package, pin, journal, predecessor, old_receipt = fixture(failing_dir)
        original_journal = journal.read_bytes()
        original_receipt = old_receipt.read_bytes()
        with patch.object(advance, '_complete', side_effect=OSError('fixture cut before COMPLETE')):
            try:
                advance.advance(project, package, pin)
            except OSError as error:
                assert str(error) == 'fixture cut before COMPLETE'
            else:
                raise AssertionError('The fixture did not interrupt installation.')
        for side in ('before', 'staged'):
            check_fresh_bootstrap(project, package / side / 'release_admission_bootstrap.py', None)
        result = advance.rollback_prepared(project, package, pin)
        assert result['state'] == 'ROLLED_BACK'
        assert journal.read_bytes() == original_journal and old_receipt.read_bytes() == original_receipt
        check_fresh_bootstrap(project, project / 'release_admission_bootstrap.py', predecessor)
        assert not (journal.parent / 'next-scan.json').exists()


if __name__ == '__main__':
    test_single_reversible_source_advance()
    print('PASS: fresh native source admission, interruption hold, and exact predecessor rollback.')

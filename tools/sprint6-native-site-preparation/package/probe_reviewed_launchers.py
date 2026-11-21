"""Exercise the existing protected launcher probes on exact disposable source."""

import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

root = Path(__file__).resolve().parent
package = root / 'payload'
backup = Path('/tmp/jsh-m1-scope-backup')
scope = json.loads((backup / 'reports/S5_S6_CONSOLIDATED_SOURCE_SCOPE_20261121.json').read_bytes())
native = Path(scope['native'])
approved = json.loads((package / 'offline_checker_inputs.json').read_bytes())['launcher_hashes']
predecessor = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')

sys.path.insert(0, str(package / 'site-source'))
from launcher_witness import LauncherPolicy, probe_launchers, verify_pinned_launch_files


def main():
    with ZipFile(predecessor / 'host-check') as checker:
        pinned = json.loads(checker.read('approved_site_policy.json'))['launchers']
    dependency_roots = tuple(map(Path, pinned['dependency_roots']))
    interpreter_target, shell = (Path(pinned[name]) for name in ('interpreter_target', 'shell'))
    with TemporaryDirectory(dir=root, prefix='launcher-probe.') as temporary:
        project = Path(temporary)
        shutil.copytree(native / 'src/job_search_helper', project / 'src/job_search_helper',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in approved['before']:
            shutil.copy2(native / name, project / name)
        interpreter = project / '.venv/bin/python'
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(interpreter_target)
        launchers = LauncherPolicy(interpreter, interpreter_target, shell, dependency_roots,
                                   approved['before'], approved['after'])
        probe_launchers(project, launchers, 'preflight', 'INSTALLED')
        for name in scope['paths']:
            if name.startswith('src/job_search_helper/') or name == 'job-search-scraper':
                shutil.copy2(package / 'candidate' / name, project / name)
        probe_launchers(project, launchers, 'admitted', 'INSTALLED')
        probe_launchers(project, launchers, 'restored', 'INSTALLED')
        verify_pinned_launch_files(project, approved['after'])
        assert not (project / '.state').exists()
    result = {'result': 'PASS_OFFLINE_EXISTING_SITE_LAUNCHER_WITNESS',
              'stages': ['preflight:before', 'admitted:after', 'restored:after'],
              'ordinary_route_checked': True, 'scratch_state_created': False,
              'source_or_service_changes_in_production': False}
    (root / 'LAUNCHER_PROBE.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

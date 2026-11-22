"""Publish one approved, locally verified note retry in its native quiet window."""

from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType


HERE = Path(__file__).resolve().parent
PROJECT = Path('/home/chris/job-search-helper_old')
RECOVERY_ENTRY = HERE / 'approved_notes_recovery_entry.py'
RECOVERY_ENTRY_SHA256 = '0ac6a0079aa9f718a8ee40718c1337bb5896fa9cd95180bc2fd4b76e56e8835f'
PRIOR_ENTRY = Path('/tmp/jsh-amphenol-production-pacing.q7WLuQwO/release_entry.py')
PRIOR_ENTRY_SHA256 = '5247f191d02598f760c49e13f6b7e61aef62762b9f74459078d1778ed5f91ca7'
NATIVE_STAGE = Path('/tmp/jsh-amphenol-note-publication-native-08')


CHILD_BOOT = '''
import sys
source = sys.argv[1]
sys.argv = [source, *sys.argv[2:]]
exec(compile(sys.stdin.buffer.read(), source, 'exec'), {'__name__': '__main__', '__file__': source})
'''


def run_child(raw, action, approval_path, approval_sha256):
    command = [sys.executable, '-I', '-B', '-X', 'pycache_prefix=/dev/null',
               '-c', CHILD_BOOT, str(RECOVERY_ENTRY), action,
               '--approval', str(approval_path), '--approval-sha256', approval_sha256]
    process = subprocess.run(command, cwd=PROJECT, input=raw, stdout=subprocess.PIPE, check=False)
    if not process.stdout:
        raise RuntimeError('The saved retry returned without a terminal report.')
    result = json.loads(process.stdout)
    if action == 'apply' and result.get('state') not in {'COMPLETE', 'RETRY_PUBLICATION_HELD'}:
        raise ValueError('The saved retry returned an unexpected application state.')
    if process.returncode and result.get('state') != 'RETRY_PUBLICATION_HELD':
        raise RuntimeError('The saved retry process did not finish cleanly.')
    return result


def main():
    parser = ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('ready', 'apply', 'restore'))
    parser.add_argument('--approval', required=True, type=Path)
    parser.add_argument('--approval-sha256', required=True)
    args = parser.parse_args()
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode or sys.pycache_prefix != '/dev/null'
            or Path(sys.prefix).resolve(strict=True) != PROJECT / '.venv'):
        raise ValueError('Run with the installed release Python -I -B -X pycache_prefix=/dev/null.')
    raw = RECOVERY_ENTRY.read_bytes()
    if sha256(raw).hexdigest() != RECOVERY_ENTRY_SHA256:
        raise ValueError('The independently approved saved retry entry changed.')
    expected = ModuleType('approved_recovery_entry')
    expected.__file__ = str(RECOVERY_ENTRY)
    exec(compile(raw, str(RECOVERY_ENTRY), 'exec'), expected.__dict__)
    file_bytes = expected.file_bytes
    attempt, cycle, release = expected.ATTEMPT, expected.CYCLE, expected.RELEASE
    approval = json.loads(file_bytes(args.approval, args.approval_sha256, private=True))
    if approval['schema'] != 'amphenol-note-publication-approval-v1':
        raise ValueError('Final approval of the locally verified note retry is required for native access.')
    native = approval['native']
    file_bytes(Path(__file__).resolve(), native['entry_sha256'])
    file_bytes(Path(native['independent_review_path']), native['independent_review_sha256'])
    prior_raw = file_bytes(PRIOR_ENTRY, PRIOR_ENTRY_SHA256)
    prior = ModuleType('measured_prior_release_entry')
    prior.__file__ = str(PRIOR_ENTRY)
    exec(compile(prior_raw, str(PRIOR_ENTRY), 'exec'), prior.__dict__)
    prior.NATIVE_STAGE = NATIVE_STAGE
    loaded = prior.verify_tool_origins()
    from job_search_helper.cli import load_environment
    from job_search_helper.integration_release import digest

    load_environment(PROJECT / '.env')
    qualification = loaded['amphenol_retry_completion'].RetryReleaseApproval.from_json(file_bytes(
        Path(approval['qualification_path']), approval['qualification_sha256'], private=True).decode())
    _candidate, manifest = qualification.read_install_inputs()
    if manifest['release_id'] != release or digest(manifest) != prior.MANIFEST_SHA:
        raise ValueError('The original measured release does not match this saved retry.')

    def qualification_check():
        _, current = qualification.read_install_inputs()
        if current != manifest:
            raise ValueError('The pinned active release qualification changed.')
        return {'release_id': release, 'manifest_sha256': prior.MANIFEST_SHA}

    window_module, modules = prior.load_native_window(loaded, native['window_sha256'])
    window = window_module.create_window(
        release_id=release, manifest_sha256=prior.MANIFEST_SHA, manifest=manifest,
        qualification_check=qualification_check, native_modules=modules,
        wrapper_scope_sha256=native['wrapper_scope_sha256'], window_root=Path(native['window_root']),
        resume_complete=True,
    )
    if args.action == 'restore':
        print(json.dumps(window.restore(), sort_keys=True))
        return 0
    if run_child(raw, 'verify-inputs', args.approval, args.approval_sha256) != {
            'state': 'NOTE_PUBLICATION_INPUTS_VERIFIED', 'attempt_id': attempt}:
        raise ValueError('Saved retry inputs failed their read-only measurement.')
    if args.action == 'ready':
        print(json.dumps(window.ready(), sort_keys=True))
        return 0

    owner = loaded['amphenol_operator_one_shot']
    host = loaded['host_server']
    coordinator_type = loaded['coordinator'].Coordinator
    with window.hold():
        base = owner._physical_directory(host.BASE / 'tasks')
        tasks = owner._physical_file(base / 'tasks.sqlite3') if base else None
        if tasks is None:
            raise ValueError('The existing coordinator store is unavailable.')
        with owner._coordinator_lease(base):
            if not owner._coordinator_is_idle(tasks):
                raise ValueError('The existing coordinator is not idle.')
            result = run_child(raw, 'apply', args.approval, args.approval_sha256)
            if result.get('state') == 'COMPLETE':
                if (set(result) != {'state', 'cycle_id', 'outcome_id'} or result['cycle_id'] != cycle
                        or not re.fullmatch('OUT-[0-9a-f]{24}', result['outcome_id'])):
                    raise ValueError('The saved retry returned a different terminal outcome.')
                enrollment = host.OperatorAmphenolRecipeEnrollment(
                    manifest['failed_request_id'], manifest['source_revision'], request_sha256=prior.REQUEST_SHA,
                )
                coordinator = coordinator_type(base=base, company_revision_resolver=host.current_company_revision,
                                               existing_store_only=True)
                settlement = loaded['amphenol_retry_completion'].deliver_qualified_operator_retry(
                    enrollment, coordinator, original_outcome=prior.OUTCOME, approval=qualification,
                )
                expected = {
                    'state': 'RECIPE_RETRY_CONFIRMED', 'attempt_id': attempt, 'outcome_id': result['outcome_id'],
                }
                result['coordinator'] = settlement
                result['state'] = 'OPERATOR_RELEASE_CONFIRMED' if settlement == expected else 'HELD_OPERATOR_TERMINAL'
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('state') == 'OPERATOR_RELEASE_CONFIRMED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

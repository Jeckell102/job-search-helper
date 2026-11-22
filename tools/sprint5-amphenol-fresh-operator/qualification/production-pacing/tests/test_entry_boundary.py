from hashlib import sha256
import json
from pathlib import Path
from shutil import copytree
import sys

import pytest

import release_entry as entry
import amphenol_retry_completion
from job_search_helper.cli import load_environment
from job_search_helper.integration_release import digest
from job_search_helper.private_file_custody import encode


STAGE = Path(__file__).parent
CANDIDATE = Path('/tmp/jsh-amphenol-production-pacing.q7WLuQwO/candidate')


class ReachedApprovedNativeLoader(Exception):
    pass


@pytest.fixture
def selected(tmp_path, monkeypatch):
    load_environment(CANDIDATE / '.env')
    shell_stage = tmp_path / 'shell'
    shell_stage.mkdir()
    for name in ('PROPOSED_MANIFEST.json', 'PREPARED.json', 'reviewed-pacing.patch'):
        (shell_stage/name).write_bytes((STAGE/name).read_bytes())
    manifest=json.loads((shell_stage/'PROPOSED_MANIFEST.json').read_bytes())
    assert digest(manifest)==entry.MANIFEST_SHA
    owner=tmp_path/'owner'
    owner.mkdir(mode=0o700)
    owner_manifest=owner/(entry.RELEASE_ID+'.manifest.json')
    owner_manifest.write_bytes(encode(manifest))
    owner_manifest.chmod(0o600)
    qualification=owner/(entry.RELEASE_ID+'.json')
    raw=encode({'schema':'integration-live-release-qualification-v1','result':'PASS','evidence_class':'live_normal_dispatch',
        'release_qualification':True,'manifest_sha256':digest(manifest),
        'candidate_validation_sha256':manifest['validation_receipt_sha256'],
        'capture_manifest_sha256':'a'*64,'reviewed_tools_sha256':'b'*64})
    status=owner.stat()
    selection=tmp_path/'selection.json'
    selection.write_bytes(encode({'release_id':entry.RELEASE_ID,'directory':str(owner),'device':status.st_dev,
        'inode':status.st_ino,'receipt_sha256':sha256(raw).hexdigest()}))
    selection.chmod(0o600)
    window_root=tmp_path/'unused-window'
    calls=[]
    def intercepted(loaded, pin):
        calls.append(pin)
        raise ReachedApprovedNativeLoader
    monkeypatch.setattr(entry,'STAGE',shell_stage)
    monkeypatch.setattr(entry,'PROJECT',tmp_path)
    monkeypatch.setattr(entry,'verify_tool_origins',lambda: {'amphenol_retry_completion':amphenol_retry_completion})
    monkeypatch.setattr(entry,'load_native_window',intercepted)
    def invoke(action, resume=False):
        argv=['release_entry',action,'--approval-record',str(selection),'--approval-record-sha256',sha256(selection.read_bytes()).hexdigest(),
            '--native-window-sha256','c'*64,'--wrapper-scope-sha256','d'*64,'--window-root',str(window_root)]
        monkeypatch.setattr(sys,'argv',argv + (['--resume-complete'] if resume else []))
        return entry.main()
    def issue_fixture_only():
        qualification.write_bytes(raw)
        qualification.chmod(0o600)
    return invoke, issue_fixture_only, owner/(entry.RELEASE_ID+'.candidate'), shell_stage, calls


def test_each_entry_action_requires_owner_even_on_recovery(selected):
    invoke, _, _, _, calls=selected
    for action, resume in [('ready',False),('apply',False),('ready',True),('apply',True),('restore',False)]:
        with pytest.raises(ValueError,match='qualification receipt is unavailable'):
            invoke(action,resume)
    assert calls == []


@pytest.mark.parametrize('candidate_status',('absent','drifted','symlink'))
def test_candidate_required_only_at_new_install_entry_gate(selected,candidate_status):
    invoke, issue, candidate, shell_stage, calls=selected
    issue()
    if candidate_status=='drifted':
        copytree(CANDIDATE,candidate)
        source=candidate/'src/job_search_helper/ats.py'
        source.write_bytes(source.read_bytes()+b'\n')
    elif candidate_status=='symlink':
        candidate.symlink_to(CANDIDATE,target_is_directory=True)
    for action in ('ready','apply'):
        with pytest.raises((ValueError, FileNotFoundError)):
            invoke(action)
    assert calls == []
    (shell_stage/'PREPARED.json').unlink()
    (shell_stage/'reviewed-pacing.patch').unlink()
    for action,resume in [('ready',True),('apply',True),('restore',False)]:
        with pytest.raises(ReachedApprovedNativeLoader):
            invoke(action,resume)
    assert calls == ['c'*64]*3

"""Disposable deterministic interleaving; never accesses production."""
from pathlib import Path
import json
import shutil
import tempfile
from test_paused_rollout import Controller, PausedRolloutTests, deployment

class SharedService(Controller):
    @property
    def running(self):
        return self.shared['running']
    @running.setter
    def running(self, value):
        self.shared['running'] = value
    def __init__(self, base, shared):
        self.shared = shared
        super().__init__(base)

with tempfile.TemporaryDirectory(prefix='qa-rollout-race-') as folder:
    root = Path(folder)
    base, prepared, archive, _ = PausedRolloutTests().fixture(root)
    prepared2, archive2 = root/'prepared2', root/'archive2'
    shutil.copytree(prepared, prepared2)
    shared = {'running': True}
    first, second = SharedService(base, shared), SharedService(base, shared)
    evidence = {}
    def interleave(phase):
        if phase == 'after_rehearsal':
            evidence['second_result'] = deployment.rollout(base, prepared2, archive2, second)['phase']
        if phase == 'after_publish_tools':
            evidence['first_published_while_service_running'] = shared['running']
            raise RuntimeError('Stop disposable reproduction after unsafe publication')
    try:
        deployment.rollout(base, prepared, archive, first, fault=interleave)
    except RuntimeError as exc:
        evidence['first_error'] = str(exc)
    evidence['first_journal'] = json.loads((archive/'journal.json').read_text())['phase']
    evidence['second_journal'] = json.loads((archive2/'journal.json').read_text())['phase']
    evidence['final_actual_source'] = (base/'tools/version').read_text()
    evidence['final_database'] = first.snapshot()['rows']
    evidence['first_rollback_error'] = json.loads((archive/'journal.json').read_text()).get('rollback_error')
    evidence['second_installed_claim_now_false'] = evidence['second_journal'] == 'INSTALLED_PAUSED' and evidence['final_database'] != [('baseline',)]
    print(json.dumps(evidence, indent=2))
    assert evidence['first_published_while_service_running']
    assert evidence['second_installed_claim_now_false']

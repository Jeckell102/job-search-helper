"""Fresh final QA: an ordinary status request must not cancel healthy inference."""
import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wrapper-workflow-20261118/host'))
import coding_tools as code
from test_campaign_completion_qa import CampaignCompletionQATests
case = CampaignCompletionQATests()
case.setUp()
started, release = threading.Event(), threading.Event()
errors = []
try:
    root = Path(case.tmp.name) / 'repo'
    (root / 'docs').mkdir(parents=True)
    (root / 'docs/wrapper-development-test-protocol.md').write_text('# Required wrapper development and test protocol\nFollow the tests.\n')
    with patch.object(code, 'ROOT', root):
        case.campaign(2)
        state = case.select()
        coordinator = case.coordinator()
        def model(*args):
            started.set()
            if not release.wait(10):
                raise RuntimeError('QA callback release timed out')
            return {'message': {'content': 'Healthy bounded response'}, 'usage': {'prompt_eval_count': 100, 'eval_count': 50}}
        coordinator.model = model
        def session():
            try:
                coordinator.session(state)
            except Exception as exc:
                errors.append(repr(exc))
        thread = threading.Thread(target=session)
        thread.start()
        assert started.wait(5), errors
        before = dict(control=case.store.campaign_control(), generation=case.store.control_generation(), status=case.store.get(state['id'])['status'])
        result = coordinator.command({'action': 'campaign-status'})
        after = dict(control=case.store.campaign_control(), generation=case.store.control_generation(), status=case.store.get(state['id'])['status'])
        release.set()
        thread.join(5)
        assert not thread.is_alive() and not errors, errors
        receipt = case.store.inference_receipts(state['id'])[0]
        evidence = dict(before=before, after=after, campaign_state=result['campaign_result']['state'], errors=result['campaign_result']['errors'], receipt_status=receipt['status'], final_task_status=case.store.get(state['id'])['status'], actual_coordinator_session=True, real_model_calls=0)
        output = Path(__file__).with_name('final-qa-live-inference-status-reproduction.json')
        output.write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps(evidence, indent=2))
finally:
    release.set()
    case.doCleanups()

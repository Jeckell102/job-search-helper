"""Run one actual host supervision callback in a fresh offline process."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch


root, phase = Path(sys.argv[1]).resolve(), sys.argv[2]
project = root / 'project'
sys.path[:0] = [str(project / 'src'), str(project / 'dev/wrapper-coder/tools')]

import host_server as host
from coordinator import Coordinator
from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository


settings = json.loads((root / 'host-settings.json').read_text())
recipe = host.AmphenolRecipeEnrollment.from_process_environment(settings['enrollment'])
success = settings['outcome']
attempt = success['identity']['attempt_id']
outcome_id = success['outcome_id']
origin = settings['original_outcome_id']
expected = {'state': 'RECIPE_RETRY_CONFIRMED', 'attempt_id': attempt, 'outcome_id': outcome_id}
model = Mock(side_effect=AssertionError('The canary host cannot invoke a model.'))
coordinator = Coordinator(root / 'coordinator', model=model,
                          company_revision_resolver=host.current_company_revision)
supervision = host.build_supervision(coordinator, recipe=recipe)
before_controls = (coordinator.store.queue_enabled(), coordinator.store.campaign_enabled(),
                   coordinator.store.pilot_task(), coordinator.store.unresolved_inferences(), coordinator.store.all())
real_command = coordinator.command
commands = []


def receive(request):
    assert phase == 'first' and request['action'] == 'ingest-scrape-outcome-delivery-v1'
    assert request['record'] == success
    commands.append(request)
    return real_command(request)


coordinator.command = receive
with (patch.object(type(recipe), '_launch', side_effect=AssertionError('Canary cannot launch a worker.')),
      patch.object(type(recipe), '_continue_release', side_effect=AssertionError('Terminal receipt must not relaunch.')),
      closing(SQLiteRepository(project / '.state/jobs.sqlite3', 'sheet', readonly=True)) as jobs):
    original_record, _, _, acknowledged, _ = OutcomeDelivery(jobs, None)._preflight(
        jobs._outcome_delivery_rows(CONSUMER, outcome_id=origin)[0],
    )
    assert acknowledged and ordinary_event_outcome_settled(jobs, original_record)
    if phase == 'restart':
        with patch.object(ManualReceiptV1HostBridge, 'manual_drain',
                          side_effect=AssertionError('Restart cannot redeliver.')):
            result = supervision.catch_up()
    else:
        result = supervision.catch_up()
    assert result == expected, result
    [sender] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=outcome_id)
    sender_receipt = json.loads(sender[6])
    with coordinator.store.connect() as receiver:
        [(receipt,)] = receiver.execute('SELECT receipt FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
                                        (outcome_id,)).fetchall()
    assert sender_receipt == json.loads(receipt) and sender_receipt['sink_status'] == 'VALIDATED_COMPLETE'
    lifecycle = coordinator.store.retry_lifecycle(attempt)
    assert lifecycle['state'] == 'VALIDATED_COMPLETE'
    assert [event['record'] for event in lifecycle['events']] == [success]
assert len(commands) == (phase == 'first')
assert before_controls == (coordinator.store.queue_enabled(), coordinator.store.campaign_enabled(),
                           coordinator.store.pilot_task(), coordinator.store.unresolved_inferences(), coordinator.store.all())
model.assert_not_called()
(root / f'host-{phase}.json').write_text(json.dumps({**expected, 'pid': __import__('os').getpid(),
    'receiver_events': len(lifecycle['events']), 'receiver_commands': len(commands),
    'receipt_sha256': sha256(receipt.encode()).hexdigest()}, sort_keys=True, indent=2) + '\n')

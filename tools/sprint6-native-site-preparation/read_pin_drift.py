"""Compare existing site-witness pins to current checkpointed stores, read-only."""

from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile

BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01')
PROJECT = Path('/home/chris/job-search-helper_old')
OWNER_PIN = 'abab8873ce31e0c0b8526f9bdcaa7ff684fc53498c3293f25b12a49092f28b96'

sys.path.insert(0, str(BUNDLE / 'site-source'))
import protected_state as witness


def main():
    with ZipFile(BUNDLE / 'host-check') as archive:
        policy = json.loads(archive.read('approved_site_policy.json'))
    pin_path = Path(policy['protected_pin_file'])
    pin_bytes = pin_path.read_bytes()
    assert sha256(pin_bytes).hexdigest() == OWNER_PIN == policy['protected_pin_sha256']
    prior = json.loads(pin_bytes)['witness']
    result = {'historical_pin_unchanged': True, 'stable_store_checks': {}, 'volatile_store_checks': []}
    compare = {
        'state': ('cycles',),
        'jobs': ('company_event_outbox', 'scrape_outcome_delivery_receipts', 'retained_publications'),
        'coordinator': ('tasks', 'inference_receipts', 'scrape_outcome_delivery_receipts'),
        'sessions': ('retained_sessions',),
    }
    for role, names in compare.items():
        try:
            with witness.database(PROJECT / witness.DATABASES[role]) as db:
                changes = [name for name in names if witness.table_digest(db, name) != prior[f'{role}/{name}']]
                flags = dict(db.execute(
                    "SELECT key,value FROM settings WHERE key IN "
                    "('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task')")) if role == 'coordinator' else None
        except witness.WitnessHold as error:
            result['volatile_store_checks'].append({'role': role, 'refusal': str(error)})
            continue
        result['stable_store_checks'][role] = {'checked': list(names), 'changed': changes}
        if flags is not None:
            result['broad_controls_remain_off'] = all(flags.get(key) == 'false' for key in witness.FLAGS)
            result['pilot_slot_is_set'] = flags.get('pilot_task', 'null') != 'null'
    assert pin_path.read_bytes() == pin_bytes
    assert any(check['changed'] for check in result['stable_store_checks'].values()), result
    result['full_live_site_snapshot_attempt'] = 'REFUSED_DATABASE_CHANGED_DURING_READ'
    result['note'] = 'Each documented store check is one stable local observation. A full current enrollment requires exclusive authority.'
    origin = Path(__file__).resolve().parent
    (origin / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

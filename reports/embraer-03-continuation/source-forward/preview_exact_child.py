"""Render a proposed child and expiry from the read-only parent verification."""

import argparse
import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


FIELDS = ('parent_task_id', 'parent_state_sha256', 'repair_key', 'outcome_id', 'record_sha256',
          'receipt_sha256', 'failure_fingerprint', 'source_revision', 'baseline_sha256')


def preview(held, expires_at):
    issued_at = int(time.time())
    if (held.get('state') not in {'EXACT_HELD_PARENT_AND_STAGED_SOURCE_MATCH',
                                  'STAGED_WRAPPER_INSTALLED_AND_EXACT_PARENT_HELD'}
            or held.get('authorization_issued') is not False
            or held.get('request_id') != 'operator-embraer-20261122-03'
            or held.get('parent_task_id') != 'WRAP-250158dc79'
            or held.get('tokens_consumed') != 118059 or held.get('tokens_remaining') != 1941
            or not issued_at < expires_at <= issued_at + 3600):
        raise ValueError('The preview needs the exact held #03 evidence and a bounded future expiry.')
    authorization = {key: held[key] for key in FIELDS}
    authorization['parent_task_state_sha256'] = authorization.pop('parent_state_sha256')
    authorization.update(schema='embraer-03-continuation-v1', issued_at=issued_at, expires_at=expires_at)
    digest = sha256(json.dumps(authorization, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {
        'status': 'PROPOSED_ONLY', 'child_task_id': 'WRAP-' + digest[:10],
        'authorization_sha256': digest, 'authorization': authorization,
        'expires_at_utc': datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        'additional_call_cap': 1, 'original_token_ceiling': 120000, 'remaining_token_allowance': 1941,
        'control_generation': held['control_generation'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('held_snapshot', type=Path)
    parser.add_argument('--expires-at', type=int, required=True, help='UTC epoch seconds')
    args = parser.parse_args()
    print(json.dumps(preview(json.loads(args.held_snapshot.read_text()), args.expires_at), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

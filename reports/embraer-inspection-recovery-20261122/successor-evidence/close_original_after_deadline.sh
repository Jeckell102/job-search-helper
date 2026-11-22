#!/usr/bin/env bash
set -euo pipefail
umask 077

stage=/tmp/jsh-embraer-owned-pilot.xXaXrqW0
python=/home/chris/job-search-helper_old/.venv/bin/python
evidence="$stage/successor-evidence"
entry="$stage/inspection-recovery/expired-post-forward/native_expired_post_forward.py"
observer=/run/jsh-s6-embraer-coordinator-recovery-13/observer.sock
args=(
    --request-id operator-embraer-20261122-01
    --request-sha256 19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2
    --entry-sha256 ff6aa8e3d59138c256962cbcddd3f2e70fac693534f57bff1d0ae3547453cce5
    --forward-receipt-sha256 9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b
    --allow-original-expired
)
printf '%s  %s\n' 'cada0b8d03ce61dc507707865aeb611facc429871ebdd81206fd7e02ea62c9ce' "$evidence/settle_expired_pilot.py" | sha256sum --check --status
"$python" -I -B "$evidence/settle_expired_pilot.py" settle > "$evidence/LIVE_EXPIRED_TASK.json"
cat "$evidence/LIVE_EXPIRED_TASK.json"
test -S "$observer"
"$python" -I -B -X pycache_prefix=/dev/null "$entry" inspect "${args[@]}" > "$evidence/LIVE_WITHDRAW_INSPECT.json"
"$python" -I -B - "$evidence/LIVE_WITHDRAW_INSPECT.json" <<'PY'
from pathlib import Path
import json,sys
value=json.loads(Path(sys.argv[1]).read_text())
assert value['state']=='EMBRAER_DISARM_NATIVE_INSPECTED'
assert value['request_id']=='operator-embraer-20261122-01'
assert value['outcome_id']=='OUT-719882e9ec8b8ad044885426'
assert value['release_id']=='REL-2a5c7bb2ad922f73cf868d15'
assert value['forward_receipt_sha256']=='9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b'
print(value['state'])
PY
"$python" -I -B -X pycache_prefix=/dev/null "$entry" disarm "${args[@]}" > "$evidence/LIVE_WITHDRAW_RECEIPT.json"
"$python" -I -B - "$evidence/LIVE_WITHDRAW_RECEIPT.json" <<'PY'
from pathlib import Path
import json,sys
value=json.loads(Path(sys.argv[1]).read_text())
assert value['state']=='EMBRAER_PILOT_WITHDRAWN'
assert value['outcome_id']=='OUT-719882e9ec8b8ad044885426'
print(json.dumps({key:value[key] for key in ('state','task_id','wrapper_pid','outcome_id')},sort_keys=True))
PY

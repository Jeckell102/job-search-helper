"""Read the exact native observer for the archived-scrape release before any service stop."""

from hashlib import sha256
from pathlib import Path
import sys


BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-owner-retirement-20261121-01')
SOCKET = Path('/run/jsh-s5-owner-retirement-01/observer.sock')
PROC = Path('/proc')
CHECKER = sys.argv[1]
require_digest = len(CHECKER) == 64 and all(c in '0123456789abcdef' for c in CHECKER)
OBSERVER = 'f4a82eaed30a46b507c525875418d4ec471b8b9147036adc67061970a5e70819'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


require(require_digest, 'Expected the independently reviewed host checker hash.')
require(sha256((BUNDLE / 'host-check').read_bytes()).hexdigest() == CHECKER,
        'The privately reviewed native checker changed.')
require(sha256(SOCKET.with_name('observer.py').read_bytes()).hexdigest() == OBSERVER,
        'The native root observer source changed.')
sys.path.insert(0, str(BUNDLE / 'site-source'))
from ancillary_process_witness import verify_ancillary_process
from host_checkpoint import (checkout_routes, unit_status, verify_listener, verify_wrapper_process,
                             WRAPPER_UNIT)
from site_policy import load_policy

policy, *_ = load_policy(str(BUNDLE / 'host-check'))
require(policy.ancillary_process_evidence == SOCKET and policy.launch_uid == 1000
        and policy.maintenance_id == 's5-owner-retirement-20261121-01' and policy.wrapper_port == 18789,
        'Native observer scope differs from the independently reviewed release.')
wrapper = unit_status(policy.systemctl, WRAPPER_UNIT)
require(wrapper['ActiveState'] == 'active', 'Wrapper service is outside its original baseline.')
pid = int(wrapper['MainPID'])
verify_wrapper_process(policy, pid, PROC)
listening = verify_listener(policy, pid, PROC)
routes = checkout_routes(policy)
for helper in (1249, 4467):
    require(verify_ancillary_process(SOCKET, PROC / str(helper), policy.launch_uid,
                                    policy.maintenance_id, routes,
                                    listener=(policy.wrapper_port, listening)) is True,
            'An enrolled native system helper could not be observed.')
print('New native observer verified both enrolled helper processes for the exact listener.')

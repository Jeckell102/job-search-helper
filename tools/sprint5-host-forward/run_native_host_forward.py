"""Wire the reviewed one-file updater to the existing MuleLab host controls."""

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


HERE = Path('/tmp/jsh-amphenol-host-forward-maintenance')
PROJECT = Path('/home/chris/job-search-helper_old')
BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03')
RECEIPT = BUNDLE.with_name('s5-amphenol-host-source-20261121-04')
STAGED = Path('/tmp/jsh-operator-owned-bridge.xu59ooer/dev/wrapper-coder/tools/host_server.py')
MANIFEST = '8c73be2432fdc49485f426f5be77d6588ea1e13f7b659595f6a4dad16710c57e'
CHECKER = 'c0bec31ab59dbdc1064e2ee7003b9aa68e115d5902c34e43ebbe75058bf2a53e'
CONTROLLER = '0f2543519bbd7dcf9737533c3e2caebf62e2e8a8cc1574d09287e21055ed1793'
PREDECESSOR = 'eecbb742a212acdfb30a7be7687daf90dd8cb348a4076b7041680ad2d1243058'
EXCHANGE = 'e35dac07cceb74964349c0daf14524e2555e213bb27ae740edc24e320765cd7b'
RESTORATION = 'c092dfc357a96f13c4b8c02740e89caa6430228239630edb80a1acadf82dcb25'
TASK = 'WRAP-6a3a372032'
INFERENCE = '2b444fe8f48a4c6e9638f1c6a7acb40c'
ADAPTER = 'a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61'
WRAPPER = 'wrapper-development-host.service'
RECIPE_CONTROLS = ('WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT', 'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT',
                   'WRAPPER_AMPHENOL_RETRY_APPROVAL', 'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE')


def checked(path, digest):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise RuntimeError(f'Changed approved input {path.name}')
    return raw


def system(*args):
    return subprocess.check_output(['/usr/bin/systemctl', '--user', *args], text=True, timeout=80).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updater-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    checked(HERE / 'deploy_host_forward.py', args.updater_sha256)
    manifest = json.loads(checked(BUNDLE / 'manifest.json', MANIFEST))
    checked(BUNDLE / 'controller.json', CONTROLLER)
    checked(BUNDLE / 'host-check', CHECKER)
    sys.path[:0] = [str(HERE), str(BUNDLE), str(BUNDLE / 'site-source')]
    from controller import Controller
    from deploy_host_forward import AFTER_SHA256, HOST_RELATIVE, apply_host_forward
    from host_checkpoint import unit_status, verify_listener, verify_wrapper_process
    from host_exchange import HostExchange
    from site_policy import load_policy

    controller = Controller(BUNDLE)
    policy, *_ = load_policy(str(BUNDLE / 'host-check'))
    candidate = checked(STAGED, AFTER_SHA256)
    scope = {name: endpoints['after']['sha256'] for name, endpoints in manifest['paths'].items() if name != HOST_RELATIVE}
    database = PROJECT / 'dev/wrapper-coder/tasks/tasks.sqlite3'
    proc = Path('/proc')

    def exchange_probe(terminal):
        if terminal['controller_journal_sha256'] != CONTROLLER or terminal['source_manifest_sha256'] != MANIFEST:
            raise RuntimeError('The enrolled predecessor changed')
        witness = HostExchange(BUNDLE / 'exchange-private/policy.json', EXCHANGE).witness('restored')
        if witness.terminal_proof_sha256 != RESTORATION or len(witness.pairs) != 3:
            raise RuntimeError('The three predecessor routes are not restored')
        return {'restored_exchange': True, 'predecessor_receipt_sha256': PREDECESSOR,
                'exchange_sha256': EXCHANGE, 'terminal_proof_sha256': RESTORATION}

    def idle():
        wrapper = unit_status(policy.systemctl, WRAPPER)
        if wrapper['ActiveState'] != 'active' or int(wrapper['MainPID']) <= 0:
            raise RuntimeError('The existing default wrapper service is inactive')
        pid = int(wrapper['MainPID'])
        verify_wrapper_process(policy, pid, proc)
        verify_listener(policy, pid, proc)
        environment = (proc / str(pid) / 'environ').read_bytes().split(b'\0')
        disabled = not any(field.startswith(tuple((key + '=').encode() for key in RECIPE_CONTROLS))
                           for field in environment)
        checked(PROJECT / 'src/job_search_helper/acquiretm.py', ADAPTER)
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            controls = dict(db.execute("SELECT key,value FROM settings WHERE key IN "
                                       "('pilot_task','queue_enabled','campaign_enabled','autopilot_enabled')"))
            state, = db.execute('SELECT state FROM tasks WHERE id=?', (TASK,)).fetchone()
            (request, status, receipt), = db.execute(
                'SELECT request_id,status,data FROM inference_receipts WHERE task=?', (TASK,),
            ).fetchall()
            count, = db.execute("SELECT count(*) FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN')").fetchone()
        if (json.loads(controls['pilot_task']) is not None or request != INFERENCE or status != 'COMPLETED'
                or json.loads(state)['status'] != 'PAUSED_ERROR'):
            raise RuntimeError('The exact settled pilot is outside its preserved state')
        return {'service': WRAPPER, 'open_inference': count, 'task_sha256': sha256(state.encode()).hexdigest(),
                'receipt_sha256': sha256(receipt.encode()).hexdigest(), 'controls': {
                    'queue': controls.get('queue_enabled') != 'false',
                    'campaign': controls.get('campaign_enabled') != 'false',
                    'autopilot': controls.get('autopilot_enabled') != 'false',
                    'unqualified_release': not disabled,
                }}

    def stop(unit):
        system('stop', unit)

    def stopped():
        if (system('show', WRAPPER, '-p', 'ActiveState', '--value') != 'inactive'
                or system('show', WRAPPER, '-p', 'MainPID', '--value') != '0'):
            raise RuntimeError('The wrapper stop did not settle')
        verify_listener(policy, 0, proc)
        return True

    def start(unit):
        system('start', unit)

    def ready():
        deadline = time.monotonic() + 12
        while True:
            try:
                return idle()
            except (OSError, RuntimeError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.3)

    if not args.apply:
        with controller.restoration_terminal() as terminal:
            exchange_probe(terminal)
            print(json.dumps({'status': 'PREFLIGHT_ONLY', 'idle': idle()}, sort_keys=True))
        return
    RECEIPT.mkdir(mode=0o700, exist_ok=False)
    result = apply_host_forward(project=PROJECT, controller=controller, candidate=candidate,
                                predecessor_receipt_sha256=PREDECESSOR, remaining_scope=scope,
                                idle_probe=idle, exchange_probe=exchange_probe, stop_service=stop,
                                stopped_probe=stopped, start_service=start, restart_probe=ready,
                                receipt_directory=RECEIPT)
    print(json.dumps({'status': result['status'], 'receipt_directory': str(RECEIPT),
                      'after_sha256': result['after_sha256']}, sort_keys=True))


if __name__ == '__main__':
    main()

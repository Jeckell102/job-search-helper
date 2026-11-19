#!/usr/bin/env python3
"""Local-only deployed F4 proof using a real authenticated wrapper request.

Run from a Jetson terminal.  It never imports or writes the receipt store.
Failure leaves an ambiguous receipt lane-blocking for operator inspection.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

TOKEN_PATH = Path('/home/chris/AI/local-ai/config/wrapper-host.json')
SETTINGS_PATH = Path('/home/chris/AI/local-ai/config/settings.json')
EVIDENCE_PATH = Path('/home/chris/AI/project-records/f4-inference-receipts-20261118/synthetic-http-orphan-recovery.json')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def generation():
    values = subprocess.check_output(
        ['systemctl', 'show', 'ollama.service', '-p', 'MainPID',
         '-p', 'ExecMainStartTimestampMonotonic', '--value'], text=True).splitlines()
    if len(values) != 2 or int(values[0]) <= 0 or int(values[1]) <= 0:
        raise RuntimeError('Ollama generation is unavailable.')
    return {'service': 'ollama.service', 'pid': int(values[0]),
            'start_monotonic': int(values[1])}


def restart_ollama():
    subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'ollama.service'], check=True)
    for _ in range(60):
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'ollama.service']).returncode == 0:
            return generation()
        time.sleep(.25)
    raise RuntimeError('Ollama did not return after the controlled restart.')


class TurnHandle:
    def __init__(self, target):
        self.result = None
        self.error = None
        self.thread = threading.Thread(target=self._run, args=(target,), daemon=False)

    def _run(self, target):
        try:
            self.result = target()
        except Exception as exc:
            self.error = exc

    def start(self):
        self.thread.start()

    def join(self, timeout):
        self.thread.join(timeout)
        return not self.thread.is_alive()


def local_service_url(settings):
    if not isinstance(settings, dict):
        raise ValueError('Invalid local service settings.')
    host, port = settings.get('listen_host'), settings.get('listen_port')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError('Local service host must be an IPv4 address.') from None
    if (address.version != 4 or address.is_unspecified or address.is_multicast
            or not (address.is_private or address.is_loopback)):
        raise ValueError('Local service host is outside the private IPv4 scope.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid local service port.')
    return 'http://' + str(address) + ':' + str(port)


def write_checkpoint(value, path=EVIDENCE_PATH):
    allowed = {'test', 'stage', 'failure_type', 'failed_after', 'pre_request_observation',
               'post_interrupt_generation', 'replacement_generation',
               'request_transport_failed', 'observed_status', 'settled_status',
               'prior_pids_absent', 'lane_released'}
    if not isinstance(value, dict) or not set(value).issubset(allowed):
        raise ValueError('Invalid synthetic proof checkpoint.')
    temp = path.with_suffix(path.suffix + '.new')
    payload = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    with temp.open('wb') as handle:
        os.chmod(temp, 0o600)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Client:
    def __init__(self, token, base_url):
        self.token = token
        self.base_url = base_url

    def _call(self, method, path, *, body=None, binding=None, timeout=20):
        headers = {'Authorization': 'Bearer ' + self.token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if binding:
            headers['X-Wrapper-Request-Fingerprint'] = binding['request_fingerprint']
            headers['X-Wrapper-Owner-Generation'] = binding['owner_generation']
        request = urllib.request.Request(self.base_url + path,
            data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def start_turn(self, payload):
        handle = TurnHandle(lambda: self._call('POST', '/api/wrapper-turn', body=payload, timeout=300))
        handle.start()
        return handle

    def status(self, binding):
        try:
            return self._call('GET', '/api/wrapper-control/' + binding['request_id'], binding=binding)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def recover(self, binding, action):
        return self._call('POST', '/api/wrapper-control/' + binding['request_id'] + '/orphan-recovery',
                          body={'action': action}, binding=binding)


def wait_status(client, binding, wanted, attempts=200):
    for _ in range(attempts):
        value = client.status(binding)
        if value and value.get('status') in wanted:
            return value
        time.sleep(.025)
    raise RuntimeError('Synthetic receipt did not reach the required state.')


def run_proof(client, *, restart=restart_ollama, get_generation=generation,
              checkpoint=lambda value: None):
    request_id = uuid.uuid4().hex
    binding = {'request_id': request_id,
               'owner_generation': digest({'synthetic_owner': request_id})}
    core = {'messages': [{'role': 'user', 'content':
             'Synthetic verification only. Write the integers 1 through 3000, one per line.'}],
            'tools': [], 'max_tokens': 3072}
    binding['request_fingerprint'] = digest(core)
    payload = {**core, **binding}
    pre_request = get_generation()
    handle = client.start_turn(payload)
    checkpoint({'test': 'synthetic-http-orphan-recovery', 'stage': 'request_started',
                'pre_request_observation': pre_request})
    wait_status(client, binding, {'RUNNING'})
    checkpoint({'test': 'synthetic-http-orphan-recovery', 'stage': 'running_observed',
                'pre_request_observation': pre_request})
    post_interrupt = restart()
    if post_interrupt == pre_request:
        raise RuntimeError('First restart did not create a distinct Ollama generation.')
    checkpoint({'test': 'synthetic-http-orphan-recovery', 'stage': 'backend_interrupted',
                'pre_request_observation': pre_request,
                'post_interrupt_generation': post_interrupt})
    if not handle.join(30):
        raise RuntimeError('Synthetic HTTP request did not terminate after backend interruption.')
    if handle.error is None:
        raise RuntimeError('Synthetic request unexpectedly returned successfully; no loss was proven.')
    wait_status(client, binding, {'UNCERTAIN'})
    observed = client.recover(binding, 'observe')
    if observed.get('status') != 'UNCERTAIN':
        raise RuntimeError('Recovery observation released the safety hold.')
    replacement = restart()
    if replacement in (pre_request, post_interrupt):
        raise RuntimeError('Second restart did not create a third generation.')
    if (os.path.exists('/proc/' + str(pre_request['pid']))
            or os.path.exists('/proc/' + str(post_interrupt['pid']))):
        raise RuntimeError('An earlier Ollama process still exists; safety hold retained.')
    checkpoint({'test': 'synthetic-http-orphan-recovery', 'stage': 'settlement_authorized',
                'pre_request_observation': pre_request,
                'post_interrupt_generation': post_interrupt,
                'replacement_generation': replacement,
                'request_transport_failed': True, 'observed_status': 'UNCERTAIN',
                'prior_pids_absent': True, 'lane_released': False})
    settled = client.recover(binding, 'settle')
    if settled.get('status') != 'FAILED':
        raise RuntimeError('Synthetic receipt was not safely settled.')
    evidence = {'test': 'synthetic-http-orphan-recovery', 'stage': 'complete',
                'pre_request_observation': pre_request,
                'post_interrupt_generation': post_interrupt,
                'replacement_generation': replacement,
                'request_transport_failed': True, 'observed_status': 'UNCERTAIN',
                'settled_status': 'FAILED', 'prior_pids_absent': True, 'lane_released': True}
    checkpoint(evidence)
    return evidence


def run_recorded_proof(client, *, path=EVIDENCE_PATH, restart=restart_ollama,
                       get_generation=generation, writer=write_checkpoint):
    """Run the proof with crash-durable checkpoints or fail before recovery."""
    started = False
    last_stage = None
    def checkpoint(value):
        nonlocal started, last_stage
        started = started or value.get('stage') == 'request_started'
        last_stage = value.get('stage')
        writer(value, path)
    try:
        evidence = run_proof(client, restart=restart, get_generation=get_generation,
                             checkpoint=checkpoint)
        return evidence
    except Exception as exc:
        if started:
            # If the first durable write failed, this second bounded record may
            # still succeed. If it cannot, propagate the persistence error and
            # leave the deployed receipt as the sole authority; never recover.
            writer({'test': 'synthetic-http-orphan-recovery', 'stage': 'failed',
                    'failed_after': last_stage, 'failure_type': type(exc).__name__}, path)
        raise


def main():
    subprocess.run(['sudo', '-v'], check=True)
    token = json.loads(TOKEN_PATH.read_text())['token']
    settings = json.loads(SETTINGS_PATH.read_text())
    run_recorded_proof(Client(token, local_service_url(settings)))
    print('PASS: real synthetic request was interrupted and settled without replay.')


if __name__ == '__main__':
    main()

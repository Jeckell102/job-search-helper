"""Verify the completed physical compensation without replaying maintenance."""

import json
import sqlite3
import stat
import subprocess
from contextlib import closing
from hashlib import sha256
from pathlib import Path

from measure_coordinator_custody import measure


ROOT = Path('/tmp/jsh-embraer-03-continuation-release')
PROJECT = Path('/home/chris/job-search-helper_old')
DATABASE = PROJECT / 'dev/wrapper-coder/tasks/tasks.sqlite3'


def hash_value(value):
    return sha256((json.dumps(value, separators=(',', ':'), sort_keys=True) + '\n').encode()).hexdigest()


def reference(path):
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Restored source path is not an exact regular file.')
    return [info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid,
            sha256(path.read_bytes()).hexdigest(), info.st_mtime_ns]


def service(name):
    output = subprocess.check_output(['/usr/bin/systemctl', '--user', 'show', name, '-p', 'ActiveState',
                                      '-p', 'UnitFileState', '-p', 'MainPID',
                                      '-p', 'ExecMainStartTimestampMonotonic'], text=True, timeout=15)
    return dict(line.split('=', 1) for line in output.splitlines())


def verify():
    tx = ROOT / 'transaction'
    raw = (tx / 'intent.json').read_bytes()
    intent = json.loads(raw)
    inspection = json.loads((ROOT / 'LIVE_INSPECTION_16_STABLE.json').read_text())
    if (intent['schema'] != 'embraer-03-five-tool-forward-v1'
            or intent['parent_task_id'] != 'WRAP-250158dc79'
            or intent['scope'] != inspection['scope'] or intent['predecessor'] != inspection['predecessor']
            or hash_value(intent['snapshot']) != intent['snapshot_sha256']
            or (tx / 'receipt.json').exists()):
        raise ValueError('This is not the exact unsealed -16 forward.')
    expected = inspection['snapshot']['existing_coordinator']
    current = measure(DATABASE)
    if (expected['existing_schema_sha256'] != current['existing_schema_sha256']
            or not current['continuation_table_exists_and_empty']
            or any(value != current['existing_tables'].get(table)
                   for table, value in expected['existing_tables'].items() if table != 'settings')):
        raise ValueError('Unexpected coordinator custody change.')

    with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute("SELECT key,value FROM settings WHERE key!='supervision_status' ORDER BY rowid").fetchall()
    controls = dict(rows)
    if controls != {'queue_enabled': 'false', 'campaign_enabled': 'false', 'autopilot_enabled': 'false',
                    'pilot_task': '"WRAP-250158dc79"', 'control_generation': '580'}:
        raise ValueError('Unexpected held coordinator controls.')
    restored_rows = [(key, '578' if key == 'control_generation' else value) for key, value in rows]
    settings_digest = sha256(b''.join(
        json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode() + b'\n' for row in restored_rows
    )).hexdigest()
    if settings_digest != expected['existing_tables']['settings']['rows_sha256']:
        raise ValueError('A coordinator setting other than the observed shutdown generation changed.')

    files = {}
    for relative, entry in intent['scope'].items():
        path = PROJECT / relative
        before = entry['before']
        if before is None:
            if path.exists() or path.is_symlink():
                raise ValueError('The added prompt survived compensation.')
            files[relative] = None
            continue
        restored = reference(path)
        if restored[2:6] != before[2:6] or sha256((tx / (path.name + '.before')).read_bytes()).hexdigest() != before[5]:
            raise ValueError('A restored source or before-image differs.')
        files[relative] = restored

    journal = (PROJECT / '.state/integration-release-journal.json').read_bytes()
    if sha256(journal).hexdigest() != intent['predecessor']['application_journal_sha256']:
        raise ValueError('The app release changed.')
    wrapper = service('wrapper-development-host.service')
    bridge = service('jetson-assistant-bridge.service')
    if (wrapper['ActiveState'] != 'active' or bridge['ActiveState'] != 'active'
            or int(wrapper['MainPID']) <= 0 or int(bridge['MainPID']) <= 0
            or any((s['ActiveState'], s['UnitFileState']) != ('inactive', 'disabled')
                   for s in (service('job-search-sync.service'), service('job-search-sync-expiry.timer')))):
        raise ValueError('The expected runtime services are not restored.')
    if measure(DATABASE) != current:
        raise ValueError('Current restoration changed during readback.')
    return {'state': 'BEFORE_SOURCE_AND_HELD_PARENT_RESTORED_UNSEALED', 'intent_sha256': sha256(raw).hexdigest(),
            'parent_task_id': intent['parent_task_id'], 'generation_before': 578, 'generation_after': 580,
            'source_references': files, 'wrapper_pid': int(wrapper['MainPID']),
            'empty_continuation_table': True, 'authorization_issued': False}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, sort_keys=True))

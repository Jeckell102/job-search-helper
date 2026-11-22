"""Read the already-approved helpers through the permanent observer."""

import argparse
from pathlib import Path
from runpy import run_path


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--maintenance-id', required=True)
    parser.add_argument('--pid', type=int, action='append', required=True)
    args = parser.parse_args()
    if len(args.pid) != 2 or len(set(args.pid)) != 2 or any(pid <= 1 for pid in args.pid):
        parser.error('Supply the two current host-check helper PIDs.')
    observer = Path('/run/jsh-maintenance-observer/observer.sock')
    installed = run_path('/usr/local/libexec/jsh-maintenance-observer/observe_once.py')
    witness = installed['load_witness']()
    proc, port = installed['PROC'], installed['LISTENER_PORT']
    inodes = witness.listening_inodes(proc, port)
    if not inodes:
        raise ValueError('Expected the running approved loopback wrapper.')
    for pid in args.pid:
        witness.verify_ancillary_process(
            observer, proc / str(pid), installed['LAUNCH_UID'], args.maintenance_id, installed['ROUTES'],
            listener=(port, inodes),
        )
    print('Permanent observer verified both helper processes and the loopback wrapper listener.')


if __name__ == '__main__':
    main()

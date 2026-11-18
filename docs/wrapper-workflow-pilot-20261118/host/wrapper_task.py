#!/usr/bin/env python3
"""Local CLI for the authenticated MuleLab coordinator service."""
import argparse
import json
from pathlib import Path
import urllib.request

from coordinator_permissions import resolve_mode


class Once(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if getattr(namespace, self.dest) is not None:
            parser.error(option_string + ' may only be provided once.')
        setattr(namespace, self.dest, value)


def parse_request(argv=None):
    parser = argparse.ArgumentParser(description='Persistent MuleLab wrapper tasks')
    parser.add_argument('action', choices=('start', 'status', 'list', 'health', 'pause', 'resume', 'pilot-start', 'pilot-stop', 'queue', 'queue-pause', 'queue-resume', 'enqueue'))
    parser.add_argument('value', nargs='?', default='')
    parser.add_argument('--max-sessions', type=int, default=None, action=Once)
    parser.add_argument('--mode', choices=('review', 'develop'), default=None, action=Once,
                        help='Task permissions; defaults to review. Develop explicitly permits development edits.')
    args = parser.parse_intermixed_args(argv)
    data = {'action': args.action}
    if args.action == 'start':
        if not args.value.strip():
            parser.error('Start requires an objective.')
        data.update(objective=args.value, max_sessions=10 if args.max_sessions is None else args.max_sessions,
                    mode=args.mode or 'review')
        try:
            resolve_mode(data)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.action == 'enqueue':
        if args.mode is not None or args.max_sessions is not None:
            parser.error('Batch files contain explicit per-company modes and limits.')
        path = Path(args.value)
        if not path.is_file() or path.stat().st_size > 350000:
            parser.error('Provide a batch JSON file smaller than 350000 bytes.')
        items = json.loads(path.read_text())
        if not isinstance(items, list):
            parser.error('Batch JSON must be a list of assignments.')
        data = {'action': 'batch', 'items': items}
    elif args.mode is not None or args.max_sessions is not None:
        parser.error('--mode and --max-sessions only apply to start.')
    elif args.action not in ('list', 'health', 'queue', 'queue-pause', 'queue-resume', 'pilot-stop'):
        if not args.value.strip():
            parser.error(args.action + ' requires a task ID.')
        data['id'] = args.value
    elif args.value:
        parser.error(args.action + ' does not accept an objective or task ID.')
    return data


def main(argv=None):
    data = parse_request(argv)
    token = (Path(__file__).resolve().parent.parent / 'bridge-token').read_text().strip()
    request = urllib.request.Request('http://127.0.0.1:18789/coordinator',
        data=json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + token,
                                               'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
        result = json.loads(response.read(100000))
    print(result.get('text') or result.get('error'))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())

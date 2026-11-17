#!/usr/bin/env python3
"""Local CLI for the authenticated MuleLab coordinator service."""
import argparse
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description='Persistent MuleLab wrapper tasks')
    parser.add_argument('action', choices=('start', 'status', 'list', 'pause', 'resume'))
    parser.add_argument('value', nargs='?', default='')
    parser.add_argument('--max-sessions', type=int, default=10)
    args = parser.parse_args()
    data = {'action': args.action}
    if args.action == 'start':
        data.update(objective=args.value, max_sessions=args.max_sessions)
    elif args.action != 'list':
        data['id'] = args.value
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

#!/usr/bin/env python3
"""Local CLI for the authenticated MuleLab coordinator service."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

from coordinator_permissions import resolve_mode


MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def read_response(response):
    """Read a complete JSON object, or fail explicitly without printing its contents."""
    body = bytearray()
    while len(body) <= MAX_RESPONSE_BYTES:
        chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)))
        if not chunk:
            break
        body.extend(chunk)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError('Coordinator response exceeds the 8 MiB safety limit; no partial status was displayed.')
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Coordinator returned malformed JSON; no status could be verified.') from exc
    if not isinstance(result, dict) or not isinstance(result.get('ok'), bool):
        raise ValueError('Coordinator returned an invalid response object; no status could be verified.')
    return result


class Once(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if getattr(namespace, self.dest) is not None:
            parser.error(option_string + ' may only be provided once.')
        setattr(namespace, self.dest, value)


def parse_request(argv=None):
    parser = argparse.ArgumentParser(description='Persistent MuleLab wrapper tasks')
    parser.add_argument('action', choices=('start', 'status', 'list', 'health', 'supervision-status', 'pause', 'resume', 'pilot-start', 'pilot-stop', 'queue', 'queue-pause', 'queue-resume', 'autopilot-start', 'autopilot-stop', 'autopilot-status', 'enqueue', 'exclude', 'include', 'retry', 'scope-expand'))
    parser.add_argument('value', nargs='?', default='')
    parser.add_argument('--max-sessions', type=int, default=None, action=Once)
    parser.add_argument('--mode', choices=('review', 'develop'), default=None, action=Once,
                        help='Task permissions; defaults to review. Develop explicitly permits development edits.')
    parser.add_argument('--approval-file', type=Path, default=None, action=Once,
                        help='Reviewed JSON containing exact scope additions, reason and expected digests.')
    parser.add_argument('--json', action='store_true', help='Print the complete status response for operator review.')
    args = parser.parse_intermixed_args(argv)
    if args.approval_file is not None and args.action != 'scope-expand':
        parser.error('--approval-file only applies to scope-expand.')
    if args.json and args.action != 'status':
        parser.error('--json only applies to status.')
    data = {'action': args.action}
    if args.action == 'scope-expand':
        if not args.value or args.mode is not None or args.max_sessions is not None or args.approval_file is None:
            parser.error('scope-expand requires a task ID and --approval-file, without mode or session options.')
        path = args.approval_file
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 20000:
            parser.error('Provide a reviewed scope approval JSON file smaller than 20000 bytes.')
        try:
            approval = json.loads(path.read_text())
        except (ValueError, OSError):
            parser.error('Cannot read scope approval JSON.')
        fields = {'paths', 'reason', 'expected_state_digest', 'expected_scope_digest'}
        if not isinstance(approval, dict) or set(approval) != fields:
            parser.error('Approval must contain exactly paths, reason, expected_state_digest and expected_scope_digest.')
        if (not isinstance(approval['paths'], list) or not approval['paths']
                or not all(isinstance(p, str) and p for p in approval['paths'])
                or not isinstance(approval['reason'], str) or not approval['reason'].strip()
                or any(not isinstance(approval[k], str) or len(approval[k]) != 64
                       or any(c not in '0123456789abcdef' for c in approval[k])
                       for k in ('expected_state_digest', 'expected_scope_digest'))):
            parser.error('Approval needs exact paths, a reason, and the current SHA256 digests.')
        data.update(id=args.value, **approval)
    elif args.action == 'start':
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
    elif args.action not in ('list', 'health', 'supervision-status', 'queue', 'queue-pause', 'queue-resume', 'pilot-stop',
                             'autopilot-start', 'autopilot-stop', 'autopilot-status'):
        if not args.value.strip():
            parser.error(args.action + ' requires a task ID.')
        data['id'] = args.value
    elif args.value:
        parser.error(args.action + ' does not accept an objective or task ID.')
    if args.json:
        data['_output_json'] = True
    return data


def main(argv=None):
    data = parse_request(argv)
    output_json = data.pop('_output_json', False)
    token = (Path(__file__).resolve().parent.parent / 'bridge-token').read_text().strip()
    request = urllib.request.Request('http://127.0.0.1:18789/coordinator',
        data=json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + token,
                                               'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
            result = read_response(response)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if data['action'] == 'supervision-status' and result.get('ok'):
        print(json.dumps(result.get('supervision'), indent=2, sort_keys=True))
    else:
        print(json.dumps(result, indent=2) if output_json else result.get('text') or result.get('error'))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())

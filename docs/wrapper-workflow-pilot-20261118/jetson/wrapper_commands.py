"""Forward explicit coordinator commands to MuleLab; never persist tasks here."""
import json
from pathlib import Path
import urllib.request

from coordinator_permissions import resolve_mode

HELP = '''MuleLab wrapper coordinator commands:
/wrapper start <objective, including tests/test_company.py>
/wrapper start --develop <objective, including tests/test_company.py>
/wrapper status <task id>
/wrapper pause <task id>
/wrapper resume <task id>
/wrapper list
/wrapper health
/wrapper queue
/wrapper queue-pause
/wrapper queue-resume
/wrapper autopilot-start
/wrapper autopilot-status
/wrapper autopilot-stop

Start defaults to review. Put --develop before the objective to explicitly authorize development edits; --review is also accepted. No-write instructions conflict with development mode and are rejected. Workers continue automatically on MuleLab using one Jetson inference slot. Live scraper validation and installation remain operator gates.'''


def parse_command(text):
    parts = text.strip().split(maxsplit=2)
    if not parts or parts[0].lower() != '/wrapper':
        return None
    if len(parts) < 2 or (parts[1].lower() == 'help' and len(parts) == 2):
        return {'action': 'help'}
    action = parts[1].lower()
    data = {'action': action}
    if action == 'start' and len(parts) == 3:
        objective = parts[2].strip()
        mode = 'review'
        if objective.startswith('--'):
            flag_parts = objective.split(maxsplit=1)
            flag = flag_parts[0]
            objective = flag_parts[1] if len(flag_parts) == 2 else ''
            if flag not in ('--review', '--develop'):
                raise ValueError('Use --review or --develop before the objective.')
            mode = flag[2:]
            objective = objective.strip()
        if not objective or any(word in ('--review', '--develop', '--mode') for word in objective.split()):
            raise ValueError('Start requires one objective and at most one mode flag before it.')
        data.update(objective=objective, mode=mode)
        resolve_mode(data)
    elif action in ('status', 'pause', 'resume') and len(parts) == 3:
        if len(parts[2].split()) != 1 or parts[2].startswith('--'):
            raise ValueError(action + ' requires one task ID and no mode flag.')
        data['id'] = parts[2]
    elif action not in ('list', 'health', 'queue', 'queue-pause', 'queue-resume',
                        'autopilot-start', 'autopilot-status', 'autopilot-stop') or len(parts) != 2:
        raise ValueError('Invalid wrapper command. Use /wrapper help.')
    return data


def command(text):
    try:
        data = parse_command(text)
    except ValueError as exc:
        return str(exc) + '\n\n' + HELP
    if data is None:
        return None
    if data['action'] == 'help':
        return HELP
    config = json.loads((Path(__file__).parent / 'config/wrapper-host.json').read_text())
    request = urllib.request.Request('http://127.0.0.1:18789/coordinator',
        data=json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + config['token'],
                                               'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
            result = json.loads(response.read(60000))
        return result.get('text') or result.get('error', 'No coordinator response.')
    except OSError:
        return 'MuleLab coordinator is unavailable. Existing tasks remain on MuleLab; no Jetson copy was created.'

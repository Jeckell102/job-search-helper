"""Forward explicit coordinator commands to MuleLab; never persist tasks here."""
import json
from pathlib import Path
import urllib.request

HELP = '''MuleLab wrapper coordinator commands:
/wrapper start <objective, including tests/test_company.py>
/wrapper status <task id>
/wrapper pause <task id>
/wrapper resume <task id>
/wrapper list

Include "fix" or "implement" to authorize development edits; otherwise the task is read-only. Workers continue automatically on MuleLab using one Jetson inference slot. Live scraper validation and installation remain operator gates.'''


def command(text):
    if not text.strip().lower().startswith('/wrapper'):
        return None
    parts = text.strip().split(maxsplit=2)
    if len(parts) < 2 or parts[1] == 'help':
        return HELP
    action = parts[1].lower()
    data = {'action': action}
    if action == 'start' and len(parts) == 3:
        data['objective'] = parts[2]
    elif action in ('status', 'pause', 'resume') and len(parts) == 3:
        data['id'] = parts[2]
    elif action != 'list':
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

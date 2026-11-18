"""One-time exact-objective migration for pre-autopilot imported tasks."""
import argparse
import json
from pathlib import Path

from coordinator_store import Store


def backfill(store, items):
    records = {}
    for item in items:
        objective, integration = item.get('objective'), item.get('integration')
        if not isinstance(objective, str) or not isinstance(integration, dict) or not integration.get('company_id'):
            raise ValueError('Every campaign record needs an objective and structured integration identity.')
        if objective in records and records[objective] != integration:
            raise ValueError('Conflicting campaign metadata for one objective.')
        records[objective] = integration
    updated = matched = 0
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
        for task_id, raw in rows:
            state = json.loads(raw)
            integration = records.get(state.get('objective'))
            if integration is None or not state.get('isolated_workspace'):
                continue
            matched += 1
            if state.get('integration'):
                if state['integration'] != integration:
                    raise ValueError('Existing task metadata conflicts: ' + task_id)
                continue
            state['integration'] = integration
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            updated += 1
    return {'records': len(records), 'matched': matched, 'updated': updated}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tasks', type=Path)
    parser.add_argument('batches', nargs='+', type=Path)
    args = parser.parse_args()
    items = []
    for path in args.batches:
        items.extend(json.loads(path.read_text()))
    print(json.dumps(backfill(Store(args.tasks), items), sort_keys=True))


if __name__ == '__main__':
    main()

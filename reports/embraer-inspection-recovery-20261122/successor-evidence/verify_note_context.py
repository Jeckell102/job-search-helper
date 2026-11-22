"""Replay only the old task's read receipts in memory with the new staged note."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import time

project=Path('/home/chris/job-search-helper_old')
sys.path.insert(0,str(project/'dev/wrapper-coder/tools'))
import coding_tools as code
from coordinator_baseline import files
from coordinator_workflow import packet,plan

stage=Path(__file__).resolve().parent
baseline=Path(json.loads((stage/'STAGED_SUCCESSOR_BASELINE.json').read_text())['private_baseline'])
manifest=files(baseline)
doc='docs/backlog/COMP-0634.md'
task='WRAP-fbb9ff24d3'
with sqlite3.connect((project/'dev/wrapper-coder/tasks/tasks.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    state=json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(task,)).fetchone()[0])
    receipts=[{**dict(row),'arguments':json.loads(row['arguments']),'result':json.loads(row['result']) if row['result'] else None}
              for row in db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id',(task,))]
matched=[item for item in receipts if item['name']=='code_read' and item['arguments'].get('path')==doc]
token=code.WORKSPACE.set(baseline)
try:
    newer=code.execute('code_read',{'path':doc,'start_line':1},{'code_read'})
finally:
    code.WORKSPACE.reset(token)
assert newer['ok'] and newer['result']['sha256']==manifest[doc]
record={'id':matched[0]['id'] if matched else max(item['id'] for item in receipts)+1,
        'phase':'inspect','name':'code_read','arguments':{'path':doc,'start_line':1},'result':newer,'created':time.time()}
replayed=[item for item in receipts if item not in matched]+[record]
current_plan=plan(state,replayed,manifest,baseline)
scenarios={}
for context in ('stopped_original_shape','new_task_shape'):
    workflow={**state['workflow'],'plan':current_plan}
    if context=='new_task_shape':
        workflow.pop('focus_receipt_id',None)
        workflow.pop('operator_guidance',None)
    selected=packet({**state,'workflow':workflow},replayed,manifest)
    note=[item for item in selected if item['arguments'].get('path')==doc]
    scenarios[context]={'note_visible':bool(note),'contains_count':bool(note and '53 jobs' in note[0]['excerpt']),
        'contains_detail_scope':bool(note and 'div.banner' in note[0]['excerpt']),
        'contains_listing_endpoint':bool(note and '/json' in note[0]['excerpt']),
        'note_excerpt_chars':len(note[0]['excerpt']) if note else 0,
        'packet_member_paths':[item['arguments'].get('path',item['tool']) for item in selected],
        'focus_receipt_id':workflow.get('focus_receipt_id')}
safe={'observed_at':datetime.now(timezone.utc).isoformat(),'note_sha256':manifest[doc],
      'note_required':doc in state['evidence_requirements']['required_files'],
      'diagnostic':scenarios,'old_receiver_receipt_rows_used_in_memory':len(receipts),'actual_task_changed':False}
(stage/'OFFLINE_NOTE_IN_REAL_CONTEXT_READBACK.json').write_text(json.dumps(safe,indent=2,sort_keys=True)+'\n')
print(json.dumps(safe,sort_keys=True))

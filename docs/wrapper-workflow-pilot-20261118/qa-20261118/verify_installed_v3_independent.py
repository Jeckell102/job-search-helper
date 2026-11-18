import json,sys,pathlib,hashlib,fcntl,datetime
q=pathlib.Path(__file__).resolve().parent;s=q.parent/'wrapper-workflow-20261118';b=pathlib.Path('/home/chris/job-search-helper_old/dev/wrapper-coder');a=b/'repairs/rollout-v3-20261118'
sys.path[:0]=[str(s),str(b/'tools')]
from rollout_controller import Controller,logical_database,paused_database
from release_bundle import digest,tree,expected_release
from coordinator_identity import validate_bound_identity
from coordinator_baseline import binding
from coordinator_store import campaign_manifest_digest
m=json.loads((q/'candidate-release-v3-manifest.json').read_text());c=Controller(s,q,m);c.inputs()
e=expected_release(m['sources'],m['prerequisites'])
for folder in ['tools','jetson']:
 assert tree(b/folder)=={k[len(folder)+1:]:v for k,v in e.items() if k.startswith(folder+'/')},folder
old=logical_database(a/'tasks-before.sqlite3');now=logical_database(b/'tasks/tasks.sqlite3');paused=paused_database(b/'tasks/tasks.sqlite3')
assert digest(old)==m['expected_database_digest'];assert paused==json.loads((a/'stopped-verification.json').read_text())
assert paused==json.loads((a/'running-verification.json').read_text())['paused']
migration=json.loads((a/'migration.json').read_text());assert migration==json.loads((a/'rehearsal.json').read_text());assert digest(now)==migration['after_digest']
assert now==logical_database(a/'rehearsal/tasks.sqlite3')
ids=set(json.loads((q/'reviewed-hold-ids.json').read_text()));before=dict(old['tasks']);after=dict(now['tasks']);assert len(ids)==102 and len(after)==111 and set(before)==set(after)
assert all(after[k]==v for k,v in before.items() if k not in ids)
for name in ['receipts','inference_receipts','batches']:assert old.get(name,[])==now.get(name,[]),name
baseline=json.loads((q/'reviewed-acceptance-baseline.json').read_text());assignment=binding(json.loads((q/'reviewed-assignment-baseline.json').read_text()))
registry=now['campaign_company_registry'];assert len(registry)==102
for k,raw in after.items():
 state=json.loads(raw);prior=json.loads(before[k])
 for key in ['calls','tokens','sessions']:assert state.get(key)==prior.get(key),(k,key)
 if k in ids:
  validate_bound_identity(state);assert state['campaign_id']=='integration-backlog-20261118';assert state['campaign_manifest_digest']==campaign_manifest_digest(state)
  assert state['acceptance_baseline_manifest']==baseline;assert state['assignment_baseline']==assignment
  assert any(k in row and state['integration_identity_digest'] in row for row in registry)
service=c.service_state();assert service['ActiveState']=='active' and service['SubState']=='running' and int(service['MainPID'])>0
health=c.health(b);assert health['ok'] is True and health['worker_alive'] is True and health['status']=='healthy'
with (b/'tasks/scheduler.lock').open('r') as lock:
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:pass
 else:
  fcntl.flock(lock,fcntl.LOCK_UN);raise AssertionError('Missing scheduler owner')
pre=json.loads((a/'before-evidence.json').read_text());assert c.unit_metadata()==pre['live_units'];remote=c.jetson_hash();assert remote==pre['jetson_forwarder_sha256']
journal=json.loads((a/'journal.json').read_text());assert journal['phase']=='INSTALLED_PAUSED' and journal['reviewed_binding']['manifest_digest']==digest(m)
result=dict(result='PASS',independent=True,manifest_digest=digest(m),verified_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),installed_trees_exact=True,source_files=len(m['sources']),prerequisite_files=len(m['prerequisites']),service=service,health=health,single_owner=True,paused=paused,migration_equals_rehearsal=True,startup_database_equals_stopped_and_rehearsal=True,reviewed_members=102,registry_rows=102,identities_and_baselines_valid=True,nonmember_tasks_preserved=9,budgets_and_historical_receipts_preserved=True,remote_forwarder_sha256=remote,service_units_unchanged=True,journal_phase=journal['phase'],production_mutations=0,live_inference_calls=0)
(q/'installed-v3-independent-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

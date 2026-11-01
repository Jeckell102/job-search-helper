"""Audited correction of an already-published fit or questions assessment to Reject.

Existing Opportunities and personal fields are retained. This module prepares
intent only; normal managed writeback/publication performs and verifies delivery.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path

from .core import reconsiderations
from .review_runtime import assessment_signature, digest, encoded, identity
from .review_writeback import history_row, opportunity_rows, requires_opportunity, sheet_writer_lock

EVENT='third_pass_published_rejection_corrected'
KIND='published_fit_or_questions_to_reject'
FIELDS={'job_key','source_hash','input_version','expected_assessment_signature',
        'expected_intent_signature','expected_publication_signature','expected_live_signature',
        'correction_id','correction_reason','assessment'}


def _saved(runtime,key,source,*,allow_missing_receipt=False):
    decision=runtime.db.execute('SELECT payload FROM decisions WHERE stage=3 AND job_key=? AND source_hash=?',(key,source)).fetchone()
    intent=runtime.db.execute('SELECT payload FROM writeback WHERE job_key=? AND source_hash=?',(key,source)).fetchone()
    receipt=runtime.db.execute('SELECT * FROM review_publications WHERE stage=3 AND job_key=? AND source_hash=?',(key,source)).fetchone()
    task=runtime.db.execute('SELECT * FROM tasks WHERE stage=3 AND job_key=? AND source_hash=?',(key,source)).fetchone()
    if not all((decision,intent,task)) or (receipt is None and not allow_missing_receipt): raise ValueError('Published exact-identity assessment, intent, receipt and task required')
    return json.loads(decision[0]),json.loads(intent[0]),dict(receipt) if receipt else {},dict(task)


def _protected(repo,key):
    if not getattr(repo,'is_local',False): return False
    rows=repo.matches('Job History',{'Job Key':key})
    return len(rows)!=1 or bool(repo.db.execute("SELECT 1 FROM manual_choices WHERE tab='Job History' AND row_id=?",(rows[0][0],)).fetchone())


def _source_guards(runtime,repo,old,key,source,*,completed_intent=None):
    if not old or old.get('Source Hash')!=source: raise ValueError('Missing History or changed source')
    if _protected(repo,key): raise ValueError('Protected manual choice prevents correction')
    own_freeze=bool(completed_intent and completed_intent.get('history_values',{}).get('Reconsideration Status')=='Frozen after 2' and completed_intent['history_values'].get('Reconsideration Count')==reconsiderations(old))
    if str(old.get('Job Status','')).casefold()=='closed' or ((str(old.get('Reconsideration Status','')).casefold()=='frozen after 2' or reconsiderations(old)>=2) and not own_freeze):
        raise ValueError('Closed or frozen History prevents correction')
    if runtime.db.execute('SELECT 1 FROM conflicts WHERE stage=3 AND job_key=? AND source_hash=?',(key,source)).fetchone():
        raise ValueError('Assessment conflict prevents correction')


def correction_snapshot(runtime,run_id,key,source,*,repo,remote=None):
    """Read only one exact published assessment and its local/live row pairs."""
    from .review_publication import _same_values
    assessment,intent,receipt,task=_saved(runtime,key,source)
    if assessment.get('run_id')!=run_id or task.get('owner') not in (None,run_id) or task.get('state')!='done':
        raise ValueError('Correction is restricted to this run completed, unchanged task')
    if assessment.get('decision') not in {'Accept','Needs Info'} or assessment.get('writeback_status')!='Written' or receipt.get('state')!='Written':
        raise ValueError('Correction requires a verified published third-pass Accept or Needs Info')
    if intent.get('pass',3)!=3 or intent.get('decision')!=assessment.get('decision') or not requires_opportunity(intent) or intent.get('marker')!='[third-pass '+digest([key,source])[:16]+']':
        raise ValueError('Original intent must prove an exact third-pass fit or questions Opportunity')
    old=history_row(repo,key); _source_guards(runtime,repo,old,key,source)
    if not _same_values(old,intent['history_values']) or intent['marker'] not in str(old.get('Review Notes','')):
        raise ValueError('Current History supersedes the published questions assessment')
    matches=opportunity_rows(repo,old)
    if len(matches)!=1 or not _same_values(matches[0],intent['opportunity_values']):
        raise ValueError('A unique unchanged questions Opportunity is required')
    if remote is None:
        if getattr(repo,'is_local',False): raise ValueError('Fresh remote read is required for a local repository')
        remote=repo
    visible=history_row(remote,key)
    if visible is None: raise ValueError('History is absent from the live workbook')
    # Compact Sheets omit local-only source/decision fields. Compare every field
    # available in both rows, including personal notes and practical fields.
    shared={k:old.get(k,'') for k in visible if k in old}
    if not _same_values(visible,shared): raise ValueError('Live History changed; preserve and reconcile')
    live_opps=opportunity_rows(remote,visible)
    if len(live_opps)!=1: raise ValueError('Unique existing live Opportunity required; correction never inserts one')
    shared_opp={k:matches[0].get(k,'') for k in live_opps[0] if k in matches[0]}
    if not _same_values(live_opps[0],shared_opp): raise ValueError('Live Opportunity changed; preserve personal fields')
    live={'history':old,'opportunity':matches[0],'remote_history':visible,'remote_opportunity':live_opps[0]}
    return {'assessment':assessment,'intent':intent,'publication':receipt,'task':task,'live':live,
            'assessment_signature':assessment_signature(assessment),'intent_signature':digest(intent),
            'publication_signature':digest(receipt),'live_signature':digest(live)}


def _request(request):
    if not isinstance(request,dict) or set(request)!=FIELDS: raise ValueError('Exact correction identity, expected signatures, provenance and revised assessment required')
    identity(request)
    if any(not isinstance(request[k],str) or not request[k].strip() for k in FIELDS-{'assessment'}):
        raise ValueError('Correction identity/signatures/provenance must be nonblank text')
    revised=request['assessment']
    if not isinstance(revised,dict) or identity(revised)!=identity(request) or revised.get('decision')!='Reject' or revised.get('fit_level') is not None:
        raise ValueError('Published questions correction is limited to exact-identity Reject with no fit level')
    if not revised.get('reason') or not revised.get('evidence_source') or not revised.get('evidence_locator') or revised.get('policy_conflicts'):
        raise ValueError('Correction requires decisive rejection evidence and no unresolved policy conflicts')
    return digest(request)


def _plan(request,snapshot):
    key,source=identity(request); old=snapshot['live']['history']; opp=snapshot['live']['opportunity']
    reason=request['assessment']['reason']; stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    marker='[third-pass correction '+digest([key,source,request['correction_id']])[:16]+']'
    values={'Review Status':'Reviewed','Review Started At':'','Decision':'Reject','Fit Level':'',
            'Added to Opportunities?':'Yes','Rejection Reason':reason,'Last Evaluated':stamp,'Description Hash':source}
    if old.get('Description Hash') and old.get('Description Hash')!=source:
        count=reconsiderations(old)+1
        values.update({'Reconsideration Count':count,'Reconsideration Status':'Frozen after 2' if count>=2 else old.get('Reconsideration Status','Eligible'),
                       'Material Change Summary':'Source version changed; substantive third-pass rejection completed.'})
    previous=str(opp.get('Review Questions','') or ''); correction='Resolved: '+reason
    present=(previous==correction or previous.startswith(correction+'\n\n') or previous.endswith('\n\n'+correction) or '\n\n'+correction+'\n\n' in previous)
    questions=previous if present else previous+('\n\n' if previous else '')+correction
    opportunity_values={'Review Questions':questions}
    operations=[{'tab':'Job History','identity':{'Job Key':key},'values':values,
                 'expected':dict(old),'append_notes':{'Review Notes':marker+' '+reason}},
                {'tab':'Opportunities','identity':{'Company':opp['Company'],'Job URL':opp['Job URL']},
                 'values':opportunity_values,'expected':dict(opp),'append_if_missing':False}]
    return {'job_key':key,'source_hash':source,'decision':'Reject','pass':3,'requires_opportunity':True,
            'preserve_existing_opportunity':True,'correction_kind':KIND,'correction_from_decision':snapshot['assessment']['decision'],'correction_id':request['correction_id'],
            'marker':marker,'history_values':values,'opportunity_values':opportunity_values,'operations':operations}


def guard_remote_correction(intent,history,opportunities):
    """Allow only the guarded before/after values during partial publication."""
    from .repository import _equivalent
    if len(opportunities)!=1: raise ValueError('Correction requires its existing unique live Opportunity')
    for operation,current,after in ((intent['operations'][0],history,intent['history_values']),
                                    (intent['operations'][1],opportunities[0],intent['opportunity_values'])):
        before=operation['expected']
        for field,value in current.items():
            if field not in before: continue
            allowed=[before[field]]
            if field in after: allowed.append(after[field])
            if field=='Review Notes':
                note=operation.get('append_notes',{}).get(field)
                if note: allowed.append(str(before[field])+('\n\n' if before[field] else '')+note)
            if not any(_equivalent(field,value,candidate) for candidate in allowed):
                raise ValueError('Live '+operation['tab']+' '+field+' changed after correction preparation')


def correct_published_questions(runtime,run_id,request,*,repo=None,remote=None,lock_path=None):
    """Prepare one narrowly guarded correction; never directly mutate Sheet rows."""
    request_signature=_request(request); key,source=identity(request)
    from .cli import get_repository,get_remote_repository,state_path
    from .sheet_profile import profile_schemas
    from .runner import _load_environment
    _load_environment(); owned=repo is None; owned_remote=False
    try:
        if repo is None: repo=get_repository(write=False,interactive=False)
        root=Path(lock_path) if lock_path is not None else state_path().parent/'writer.lock'
        with ExitStack() as stack:
            stack.enter_context(sheet_writer_lock(root))
            if getattr(repo,'is_local',False): stack.enter_context(sheet_writer_lock(root.parent/'review-writeback.lock'))
            _,run=runtime._run(3,run_id)
            if not run or run['state']!='active' or run['lease_until']<=runtime.clock(): raise ValueError('Active own third-pass run required')
            previous_event=runtime.db.execute("SELECT detail FROM events WHERE event=? AND json_extract(detail,'$.correction_id')=?",(EVENT,request['correction_id'])).fetchone()
            if previous_event:
                audit=json.loads(previous_event[0]); saved,intent,receipt,task=_saved(runtime,key,source,allow_missing_receipt=True)
                if audit.get('request_signature')!=request_signature or audit.get('request')!=request or assessment_signature(saved)!=assessment_signature(audit['corrected_assessment']) or intent!=audit['intent']:
                    raise ValueError('Correction ID or corrected assessment/intent changed')
                if task.get('owner') not in (None,run_id) or task.get('version')!=request['input_version']: raise ValueError('Corrected task identity changed')
                _source_guards(runtime,repo,history_row(repo,key),key,source,completed_intent=intent)
                return {'pass':3,'run_id':run_id,'corrected':0,'reused':1,'job_key':key,'source_hash':source,'correction_id':request['correction_id'],'next_action':'WRITEBACK_REQUIRED'}
            if remote is None and getattr(repo,'is_local',False):
                remote=get_remote_repository(write=False,interactive=False,schemas=profile_schemas(repo.get_meta('sheets_profile')),evidence_archives=False); owned_remote=True
            snapshot=correction_snapshot(runtime,run_id,key,source,repo=repo,remote=remote)
            for field in ['assessment','intent','publication','live']:
                if request['expected_'+field+'_signature']!=snapshot[field+'_signature']: raise ValueError('Expected '+field+' changed; correction not prepared')
            if snapshot['task']['version']!=request['input_version']: raise ValueError('Review input version changed')
            proposed=request['assessment']; runtime.validate_result(3,proposed)
            for field,value in [('run_id',run_id),('pass',3),('input_version',request['input_version'])]:
                if field in proposed and proposed[field]!=value: raise ValueError('Correction cannot change review ownership/version')
            original=snapshot['assessment']; corrected={**original,**{k:proposed[k] for k in ['decision','fit_level','reason','evidence_source','evidence_locator','policy_conflicts'] if k in proposed}}
            corrected.update(corrected_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),correction_id=request['correction_id'],writeback_status='Pending',writeback_detail='Audited published questions correction awaiting verified delivery')
            intent=_plan(request,snapshot)
            with runtime.transaction():
                # Network reads above never hold the runtime write transaction.
                current=_saved(runtime,key,source)
                if any(digest(value)!=digest(expected) for value,expected in zip(current,[snapshot['assessment'],snapshot['intent'],snapshot['publication'],snapshot['task']])):
                    raise ValueError('Saved assessment or delivery changed during correction checks')
                runtime._owned(3,run_id)
                runtime.db.execute('UPDATE decisions SET payload=?,updated=? WHERE stage=3 AND job_key=? AND source_hash=?',(encoded(corrected),runtime.clock(),key,source))
                runtime.db.execute('UPDATE writeback SET payload=? WHERE job_key=? AND source_hash=?',(encoded(intent),key,source))
                runtime.db.execute('DELETE FROM review_publications WHERE stage=3 AND job_key=? AND source_hash=?',(key,source))
                runtime.event(3,key,source,EVENT,encoded({'correction_id':request['correction_id'],'request':request,'request_signature':request_signature,'prior':snapshot,'corrected_assessment':corrected,'intent':intent}))
        runtime.export(3); runtime.checkpoint(3,run_id)
        return {'pass':3,'run_id':run_id,'corrected':1,'reused':0,'job_key':key,'source_hash':source,'correction_id':request['correction_id'],'next_action':'WRITEBACK_REQUIRED'}
    finally:
        if owned_remote and hasattr(remote,'close'): remote.close()
        if owned and hasattr(repo,'close'): repo.close()

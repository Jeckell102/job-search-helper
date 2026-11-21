from pathlib import Path
from types import SimpleNamespace
from hashlib import sha256
from dataclasses import replace
import json
import sqlite3
import pytest

import amphenol_candidate_release as reader
import amphenol_recipe_choice_input as choice
from amphenol_recipe_candidate import save_candidate
from amphenol_retry_completion import RetryReleaseApproval
from acquiretm_membership_recipe import TARGET_PATH, SOURCE_SHA256, W1
from coordinator import AMPHENOL_RECIPE_WORK_ORDER
from coordinator_inference import digest
from coordinator_store import Store
from job_search_helper.integration_release import (MANIFEST_SCHEMA, metadata,
    source_tree_digest, config_tree_digest, manifest_release_id, digest as release_digest)
from job_search_helper.private_file_custody import encode
from job_search_helper.temporary_retry import _selected_sha


@pytest.fixture
def case(tmp_path, monkeypatch):
    store=Store(tmp_path/'tasks')
    project=tmp_path/'canonical'
    source=project/TARGET_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes((Path(__file__).parent/'baseline.py').read_bytes())
    assert sha256(source.read_bytes()).hexdigest()==SOURCE_SHA256
    task_id='WRAP-1234567890';outcome_id='OUT-'+'1'*24;repair_key='2'*64
    request_id='operator-fresh-reader-fixture';revision='3'*64;request_sha='4'*64
    evidence={'page':2,'advertised_total':2,'first_page_count':1,'refreshed_page_count':1,
        'premature_elapsed_ms':1,'refreshed_elapsed_ms':2,
        'first_page_ids_sha256':'5'*64,'premature_page_ids_sha256':'5'*64,
        'refreshed_page_ids_sha256':'6'*64}
    binding={'request_id':request_id,'outcome_id':outcome_id,'company_id':'COMP-0490',
        'source_revision':revision,'board':W1['source'],'witness_sha256':_selected_sha(evidence)}
    prepared={'binding':binding,'messages':[{'role':'system','content':'fixture'},
        {'role':'user','content':json.dumps({'W1':evidence})}],'tools':[]}
    inference_id='7'*32
    receipt={'task':task_id,'phase':'inspect','status':'COMPLETED','request_id':inference_id,
        'accepted_recipe_choice':dict(reader._CHOICE),'response_digest':'8'*64,
        'prompt_digest':digest(prepared['messages']),'tools_digest':digest(prepared['tools']),
        'control_binding':{'request_id':inference_id,'request_fingerprint':'9'*64,'owner_generation':'a'*64}}
    task={'id':task_id,'status':'REVIEW_COMPLETE_LIVE_NOT_VALIDATED','stop_requested':False,
        'mode':'review','phase':'inspect','isolated_workspace':True,'baseline_passed':True,
        'integration':{'work_order':AMPHENOL_RECIPE_WORK_ORDER},'held_repair_key':repair_key,
        'repair_provenance':{'repair_key':repair_key,'outcome_id':outcome_id,'company_id':'COMP-0490','source_revision':revision}}
    with store.connect() as db:
        db.execute('INSERT INTO tasks VALUES (?,?)',(task_id,json.dumps(task)))
        db.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',(inference_id,task_id,'COMPLETED',json.dumps(receipt)))
        db.execute('INSERT INTO repair_intake(repair_key,outcome_id,company_id,source_revision,status,task_id,payload,received) VALUES (?,?,?,?,?,?,?,?)',
            (repair_key,outcome_id,'COMP-0490',revision,'PROMOTED_PAUSED',task_id,'{}',1))
        db.execute('INSERT INTO repair_intake_evidence VALUES (?,?)',(repair_key,outcome_id))
    task_root=store.base/task_id;task_root.mkdir()
    sparse=save_candidate(task_root,project,prepared,receipt)
    stale=tmp_path/'stale-workspace';(stale/TARGET_PATH).parent.mkdir(parents=True)
    (stale/TARGET_PATH).write_text('stale = True\n')
    def forbidden_workspace(*args,**kwargs):
        pytest.fail('Fresh operator reader entered stale task workspace')
    monkeypatch.setattr(reader,'workspace',forbidden_workspace)
    monkeypatch.setattr(reader.coding_tools,'root',lambda:stale)
    candidate=tmp_path/'candidate';(candidate/TARGET_PATH).parent.mkdir(parents=True)
    (candidate/TARGET_PATH).write_bytes((sparse/TARGET_PATH).read_bytes())
    manifest={'schema':MANIFEST_SCHEMA,'failed_request_id':request_id,'company_id':'COMP-0490',
        'source_revision':revision,'files':{TARGET_PATH:{'before':metadata(source),'after':metadata(candidate/TARGET_PATH)}},
        'before_source_manifest_sha256':source_tree_digest(project),'source_manifest_sha256':source_tree_digest(candidate),
        'before_config_sha256':config_tree_digest(project),'config_sha256':config_tree_digest(candidate),
        'dependency_manifest_sha256':'b'*64,'validation_receipt_sha256':'c'*64}
    manifest['release_id']=manifest_release_id(manifest)
    authority=tmp_path/'qualification';authority.mkdir(mode=0o700)
    qualification=authority/(manifest['release_id']+'.json')
    raw=encode({'schema':'integration-live-release-qualification-v1','result':'PASS',
        'evidence_class':'live_normal_dispatch','release_qualification':True,
        'manifest_sha256':release_digest(manifest),'candidate_validation_sha256':manifest['validation_receipt_sha256'],
        'capture_manifest_sha256':'d'*64,'reviewed_tools_sha256':'e'*64})
    qualification.write_bytes(raw);qualification.chmod(0o600)
    identity=authority.stat()
    approval=RetryReleaseApproval(manifest['release_id'],str(authority),identity.st_dev,identity.st_ino,sha256(raw).hexdigest())
    enrollment=SimpleNamespace(request_id=request_id,source_revision=revision,request_sha256=request_sha)
    root=tmp_path/'application';root.mkdir()
    def source_io(actual_root,**kwargs):
        assert actual_root==root and kwargs=={'outcome_id':outcome_id,'request_sha256':request_sha,'source_revision':revision}
        return {'stale':False,'acknowledged':True,'record':{'outcome_id':outcome_id,'identity':binding}}
    def choice_io(actual_root,actual_store,**kwargs):
        assert actual_root==root and actual_store is store
        assert kwargs=={'outcome_id':outcome_id,'request_sha256':request_sha,'enabled':True,'expected_task_id':task_id}
        return prepared
    monkeypatch.setattr(choice,'read_operator_owned_source',source_io)
    monkeypatch.setattr(choice,'read_operator_owned_choice_input',choice_io)
    coordinator=SimpleNamespace(store=store)
    def read(**overrides):
        args={'outcome_id':outcome_id,'candidate_root':candidate,'manifest':manifest,
            'completed_task_id':task_id,'canonical_baseline':project,'approval':approval}
        args.update(overrides)
        return reader.read_operator_generated_candidate_release(enrollment,coordinator,root,**args)
    return SimpleNamespace(**locals())


def test_fresh_complete_uses_canonical_baseline_and_real_qualification(case):
    before=case.store.path.read_bytes()
    result=case.read()
    assert result=={'candidate_root':case.candidate,'manifest':case.manifest,'approval':case.approval,'task_id':case.task_id}
    assert case.read()==result and case.store.path.read_bytes()==before


def test_wrong_task_and_paused_error_hold(case):
    assert case.read(completed_task_id='WRAP-0000000000') is None
    case.task['status']='PAUSED_ERROR'
    with case.store.connect() as db:db.execute('UPDATE tasks SET state=? WHERE id=?',(json.dumps(case.task),case.task_id))
    assert case.read() is None


@pytest.mark.parametrize('name',[TARGET_PATH,'reviewed.patch','build-receipt.json'])
def test_truncated_task_artifact_holds(case,name):
    artifact=case.sparse/name;artifact.write_bytes(artifact.read_bytes()[:-1])
    assert case.read() is None


def test_forged_task_build_receipt_holds(case):
    artifact=case.sparse/'build-receipt.json';value=json.loads(artifact.read_bytes());value['response_digest']='0'*64
    artifact.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    assert case.read() is None


def test_changed_baseline_and_qualification_hold(case):
    original=case.source.read_bytes();case.source.write_bytes(original+b'\n')
    assert case.read() is None
    case.source.write_bytes(original)
    case.qualification.write_bytes(b'{}')
    assert case.read() is None


def test_approval_release_identity_must_match_selected_manifest(case):
    assert case.read(approval=replace(case.approval,release_id='REL-'+'f'*24)) is None


def test_candidate_root_direct_alias_is_not_physical_input(case):
    alias=case.tmp_path/'candidate-alias'
    alias.symlink_to(case.candidate,target_is_directory=True)
    assert case.read(candidate_root=alias) is None

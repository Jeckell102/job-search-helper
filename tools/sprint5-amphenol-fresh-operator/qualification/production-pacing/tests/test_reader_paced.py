from pathlib import Path
from types import SimpleNamespace
from hashlib import sha256
from dataclasses import replace
import json
from shutil import copytree
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
def paced_case(tmp_path, monkeypatch, request):
    store=Store(tmp_path/'tasks')
    project=tmp_path/'canonical'
    source=project/TARGET_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes((Path(__file__).parent/'baseline.py').read_bytes())
    assert sha256(source.read_bytes()).hexdigest()==SOURCE_SHA256
    frozen=Path(__file__).parent
    identity=json.loads((frozen/'PREPARED.json').read_bytes())
    variant=getattr(request,'param','exact')
    task_id=identity['task_id'] if variant!='foreign-task' else 'WRAP-0123456789'
    outcome_id=identity['outcome_id'] if variant!='foreign-outcome' else 'OUT-'+'1'*24
    repair_key='2'*64
    request_id=identity['failed_request_id'];revision=identity['source_revision'];request_sha=identity['request_sha256']
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
    assert sha256((sparse/TARGET_PATH).read_bytes()).hexdigest() == identity['build_artifacts'][TARGET_PATH]
    candidate=tmp_path/'candidate'
    copytree(frozen/'frozen-candidate', candidate)
    from job_search_helper.cli import load_environment
    load_environment(candidate/'.env')
    manifest=json.loads((frozen/'PROPOSED_MANIFEST.json').read_bytes())
    assert release_digest(manifest) == identity['manifest_sha256']
    assert manifest['release_id'] == identity['release_id']
    source.chmod(manifest['files'][TARGET_PATH]['before']['mode'])
    assert metadata(source) == manifest['files'][TARGET_PATH]['before']
    assert metadata(candidate/TARGET_PATH) == manifest['files'][TARGET_PATH]['after']
    assert source_tree_digest(candidate)==manifest['source_manifest_sha256']
    assert config_tree_digest(candidate)==manifest['config_sha256']
    if variant=='foreign-release':
        manifest['validation_receipt_sha256']='f'*64
        manifest['release_id']=manifest_release_id(manifest)
        assert manifest['release_id'] != identity['release_id']
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



def test_exact_paced_release_preserves_genuine_generated_artifacts_and_uses_fixture_owner(paced_case):
    case = paced_case
    artifacts = lambda: {name: (case.sparse / name).read_bytes() for name in (TARGET_PATH, 'reviewed.patch', 'build-receipt.json')}
    old = artifacts()
    result = case.read()
    assert result == {'candidate_root':case.candidate,'manifest':case.manifest,'approval':case.approval,'task_id':case.task_id}
    assert artifacts() == old and case.read() == result


@pytest.mark.parametrize('paced_case', ('foreign-task','foreign-outcome','foreign-release'), indirect=True)
def test_coherent_other_owner_or_release_cannot_select_paced_bytes(paced_case):
    assert paced_case.read() is None


@pytest.mark.parametrize('target', ('paced-image', 'other-source', 'generated-receipt', 'qualification-receipt'))
def test_changed_bytes_or_receipts_refuse_selected_paced_release(paced_case, target):
    case=paced_case
    if target=='paced-image': path=case.candidate/TARGET_PATH
    elif target=='other-source': path=case.candidate/'src/job_search_helper/ats.py'
    elif target=='generated-receipt': path=case.sparse/'build-receipt.json'
    else: path=case.qualification
    path.write_bytes(path.read_bytes()+b'\n')
    assert case.read() is None

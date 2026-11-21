"""Actual qualified owner/launcher/worker with fresh synthetic operator origin."""
from contextlib import closing,redirect_stdout
from hashlib import sha256
from io import StringIO
import json,os,shutil,sqlite3,subprocess,sys,traceback
from pathlib import Path
from tempfile import mkdtemp
HERE=Path(__file__).resolve().parent
SOURCE=Path('/home/chris/job-search-helper_old')
STAGED=Path('/tmp/jsh-operator-owned-bridge.xu59ooer')
TARGET='src/job_search_helper/acquiretm.py'
PINS={'src/job_search_helper/qualified_release_owner.py':'5cf4e70829ad40d797dde4779cb6a1f0a75953f303ed330c0610ee7f0e5b23e6','src/job_search_helper/runner.py':'de3c0f5045e1ad07d0b1e2e8b1da8b8dbce2acd3767182ddf9d1c7dbbaefb87b','job-search-scraper':'8fb9939560f004a213ca94724cdada7734996072c31194679017fea492841f72','release_admission_bootstrap.py':'1258ac47b647d61361fa84ccdda14816a184e6c15cd4c6e7c78e6b27cd228d45'}
def sha(path):return sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def snapshot(directory):
    result={}
    for name in ('state.db','jobs.sqlite3','inventories.sqlite3'):
        with closing(sqlite3.connect((directory/name).as_uri()+'?mode=ro',uri=True)) as db:result[name]=list(db.iterdump())
    return result

def main():
    sys.addaudithook(lambda event,args: (_ for _ in ()).throw(AssertionError('No network')) if event.startswith('socket.') else None)
    root=Path(mkdtemp(prefix='run-',dir=HERE));print(root,flush=True)
    write(HERE/'LATEST.json',{'root':str(root)})
    project=root/'project';candidate=root/'candidate';approval=root/'approval'
    project.mkdir(mode=0o700);approval.mkdir(mode=0o700)
    for name,pin in PINS.items():assert sha(SOURCE/name)==pin,(name,sha(SOURCE/name))
    # Only Python application sources; no native data, configuration or credentials.
    for path in (SOURCE/'src/job_search_helper').rglob('*.py'):
        rel=path.relative_to(SOURCE);target=project/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    for name in ('job-search-scraper','release_admission_bootstrap.py'):shutil.copy2(SOURCE/name,project/name)
    shutil.copytree(STAGED/'tests',project/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name,body in (('.storage-backend','sqlite\n'),('requirements.txt','# Offline standard library fixture\n'),('title-blacklist.txt',''),('title-review-list.txt','')):(project/name).write_text(body)
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(project/'.venv')],check=True)
    site=next((project/'.venv/lib').glob('python*/site-packages'))
    shutil.copy2(HERE/'offline_child.py',site/'offline_child.py');(site/'offline_child.pth').write_text('import offline_child\n')
    shutil.copytree(project/'src',candidate/'src')
    for name in ('.storage-backend','requirements.txt','title-blacklist.txt','title-review-list.txt'):shutil.copy2(project/name,candidate/name)
    # The fixture candidate below uses the real fixed compiler after retaining the synthetic choice.
    directory=project/'.state';directory.mkdir(mode=0o700)
    for key in list(os.environ):
        if key.startswith(('JOB_','JSH_','WRAPPER_','COMPANY_RETAINED_','GOOGLE_')) or key in {'SPREADSHEET_ID','STATE_DB_FILE','EVIDENCE_ARCHIVES_FILE'}:os.environ.pop(key)
    os.environ.update(JOB_STORAGE_BACKEND='sqlite',STATE_DB_FILE='.state/state.db',JOB_DB_FILE='.state/jobs.sqlite3',SPREADSHEET_ID='fixture-sheet',PYTHONDONTWRITEBYTECODE='1')
    tool_root = project / 'dev/wrapper-coder/tools'
    tool_root.mkdir(parents=True)
    for tool in (SOURCE / 'dev/wrapper-coder/tools').glob('*.py'):
        shutil.copyfile(tool, tool_root / tool.name)
    shutil.copyfile(
        '/tmp/jsh-amphenol-operator-terminal.2nqf6fxc/amphenol_retry_completion.py',
        tool_root / 'amphenol_retry_completion.py',
    )
    shutil.copyfile('/tmp/jsh-amphenol-operator-resume.chrelmha/amphenol_operator_retained_release.py', tool_root / 'amphenol_operator_retained_release.py')
    for name in ('amphenol_operator_one_shot.py', 'coordinator.py', 'coordinator_store.py'):
        shutil.copyfile(Path('/tmp/jsh-amphenol-one-shot.24kytov3') / name, tool_root / name)
    for name in ('amphenol_operator_quiet_window.py', 'controller.py', 'gate.py', 'installer.py'):
        shutil.copyfile(Path('/tmp/jsh-amphenol-maintenance-bound.dnym8mf_') / name, tool_root / name)
    token = tool_root.parent / 'bridge-token'
    token.write_text('fixture-token\n')
    token.chmod(0o600)
    sys.path[:0]=[str(project/'src'),str(project/'tests'),str(tool_root),str(HERE)]
    from job_search_helper.ats import Inventory
    from job_search_helper.company_events import current_company_source_revision
    from job_search_helper.engine import Engine,State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.integration_release import MANIFEST_SCHEMA,config_tree_digest,dependency_manifest_digest,digest,manifest_release_id,metadata,source_tree_digest
    from job_search_helper.operator_company_request import queue_operator_company_request
    from job_search_helper.qualified_release_owner import release_and_continue_qualified
    from job_search_helper.repository import SCHEMAS
    from job_search_helper.scan_request import requested_scan
    from job_search_helper.sheet_profile import COMPACT_PROFILE
    from job_search_helper.sqlite_repository import SQLiteRepository
    from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication
    company={'Company ID':'COMP-0490','Company':'Amphenol Aerospace','Company Status':'Active','ATS / Source':'AcquireTM','Official Careers URL':'https://amphenol-aerospace.acquiretm.com/home.aspx'}
    other={'Company ID':'COMP-OTHER','Company':'Other Fixture','Company Status':'Active','ATS / Source':'Greenhouse','Official Careers URL':'https://boards.greenhouse.io/fixture-other'}
    other_job={'Job Key':'other-existing','Company':'Other Fixture','Job Title':'Untouched fixture job','Job URL':'https://example.invalid/other'}
    request_id='operator-amphenol-disposable-qualification-proof'
    db=directory/'state.db';jobs_path=directory/'jobs.sqlite3'
    try:
        with closing(State(db)) as state,closing(SQLiteRepository(jobs_path,'fixture-sheet',initialize=True)) as jobs,closing(InventoryInbox(directory/'inventories.sqlite3','fixture-sheet')) as inbox:
            for tab in SCHEMAS:jobs.import_rows(tab,enumerate([company,other] if tab=='Companies' else [other_job] if tab=='Job History' else [],2))
            jobs.set_meta('ready','yes');jobs.set_meta('sheets_profile',COMPACT_PROFILE);jobs.ensure_columns('Opportunities',['Opportunity ID'])
            write(project/'workbook-before.json',{'Companies':jobs.read('Companies'),'Job History':jobs.read('Job History')})
            assert queue_operator_company_request(jobs,directory,company['Company ID'],request_id)['state']=='REQUEST_WRITTEN'
            from unittest.mock import patch
            from job_search_helper.cli import writer_lock
            from job_search_helper.operator_amphenol_settlement import settle_operator_amphenol
            from job_search_helper.operator_company_request import _digest
            from job_search_helper.ordinary_event_settlement import ACQUIRETM_PAGINATION_CODE
            request=json.loads((directory/'next-scan.json').read_bytes())
            engine=Engine(jobs,state,inbox=inbox,runtime_binding={'state':'NO_RELEASE','source_manifest_sha256':source_tree_digest(project)})
            with writer_lock(directory/'scraper.lock'),writer_lock(directory/'writer.lock'):
                original=requested_scan(engine,state,db)
                observation={'sha256':'b'*64,'inventory_sha256':'c'*64,'inventory':{'outcome_failure':{'evidence_code':ACQUIRETM_PAGINATION_CODE}}}
                with patch('job_search_helper.operator_amphenol_settlement.load_operator_amphenol_partial',return_value=observation):
                    settled=settle_operator_amphenol(engine,request_sha256=_digest(request))
                assert settled['state']=='FETCH_REPAIR_QUALIFIED' and settled['cycle_id']==original
            prior=state.cycle(original)
            assert prior['status']=='Complete with exceptions',prior
            assert prior['operator_request']['request_id']==request_id and not prior.get('company_event')
            mirror=jobs.matches('Scan Cycles',{'Cycle ID':original})[0][1]
            saved_other=jobs.matches('Companies',{'Company ID':'COMP-OTHER'})[0][1];saved_job=jobs.matches('Job History',{'Job Key':'other-existing'})[0][1]
            revision_value=current_company_source_revision(jobs,company['Company ID'])
        assert not (directory/'company-event-bridge').exists()
        request_archive=(directory/'last-scan-request.json').read_bytes()
        posting={'company_id':company['Company ID'],'company':company['Company'],'ats':'AcquireTM','posting_id':'fixture-1','url':company['Official Careers URL']+'/jobs/fixture-1','title':'Field Applications Engineer','description':'Integrate products and support technical customers. '*80,'location':'Ohio','work_arrangement':'Hybrid','compensation':'$140k-$180k annual base','is_listed':True}
        write(project/'provider-fixture.json',{'jobs':[posting],'company':company})
        def revision(cid):
            with closing(SQLiteRepository(jobs_path,'fixture-sheet',readonly=True)) as jobs:return current_company_source_revision(jobs,cid)
        from acquiretm_membership_recipe import W1, SELECTION, build_current_owned
        from coordinator_inference import digest as inference_digest
        from job_search_helper.temporary_retry import _selected_sha

        evidence = W1['failure']['evidence']
        original_outcome = settled['outcome']['outcome_id']
        historical_task = 'WRAP-1111111111'
        inference_id = '1' * 32
        source_binding = {
            'board': company['Official Careers URL'],
            'outcome_id': original_outcome, 'request_id': request_id,
            'company_id': company['Company ID'], 'source_revision': revision_value,
            'witness_sha256': _selected_sha(evidence),
        }
        prepared = {'binding': source_binding,
                    'messages': [{'role': 'system', 'content': 'Synthetic test evidence projection'},
                                 {'role': 'user', 'content': json.dumps({'W1': evidence})}],
                    'tools': []}
        historical_receipt = {
            'task': historical_task, 'phase': 'inspect', 'request_id': inference_id, 'status': 'COMPLETED',
            'accepted_recipe_choice': {'summary': 'W1', 'next_action': 'listing_membership_change',
                                       'outcome': 'phase_done'},
            'control_binding': {'request_id': inference_id, 'request_fingerprint': '2' * 64,
                                'owner_generation': '3' * 64},
            'prompt_digest': inference_digest(prepared['messages']), 'tools_digest': inference_digest([]),
            'response_digest': '4' * 64,
        }
        built = build_current_owned((project / TARGET).read_bytes(), SELECTION, source_binding['board'],
                                    evidence, source_binding)
        (candidate / TARGET).write_text(built['source'])
        (candidate / 'reviewed.patch').write_text(built['diff'])
        record = {**built['receipt'], 'request_id': inference_id,
                  'response_digest': historical_receipt['response_digest'],
                  'outcome_id': original_outcome, 'company_id': company['Company ID'],
                  'source_revision': revision_value}
        write(candidate / 'build-receipt.json', record)
        verification = {
            'schema': 'amphenol-installed-recipe-verification-v1', 'result': 'PASS',
            'wrapper': metadata(candidate / TARGET), 'source_manifest_sha256': source_tree_digest(candidate),
            'config_sha256': config_tree_digest(candidate),
            'dependency_manifest_sha256': dependency_manifest_digest(project),
        }
        manifest={'schema':MANIFEST_SCHEMA,'company_id':company['Company ID'],'source_revision':revision_value,'failed_request_id':request_id,'files':{TARGET:{'before':metadata(project/TARGET),'after':metadata(candidate/TARGET)}},'before_source_manifest_sha256':source_tree_digest(project),'source_manifest_sha256':source_tree_digest(candidate),'dependency_manifest_sha256':dependency_manifest_digest(project),'before_config_sha256':config_tree_digest(project),'config_sha256':config_tree_digest(candidate),'validation_receipt_sha256':digest(verification)}
        manifest['release_id']=manifest_release_id(manifest);write(root/'manifest.json',manifest)
        selected_candidate = approval / (manifest['release_id'] + '.candidate')
        candidate.rename(selected_candidate)
        candidate = selected_candidate
        selected_manifest = approval / (manifest['release_id'] + '.manifest.json')
        selected_manifest.write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')))
        selected_manifest.chmod(0o600)
        ticket=approval/(manifest['release_id']+'.json')
        # Exact authority-shape fixture only. This is NOT live qualification.
        write(ticket,{'schema':'integration-live-release-qualification-v1','result':'PASS','evidence_class':'live_normal_dispatch','release_qualification':True,'manifest_sha256':digest(manifest),'capture_manifest_sha256':sha(project/'provider-fixture.json'),'candidate_validation_sha256':digest(verification),'reviewed_tools_sha256':sha(HERE/'offline_child.py')});ticket.write_text(json.dumps(json.loads(ticket.read_text()),sort_keys=True,separators=(',',':')));ticket.chmod(0o600)
        info=approval.stat();checks=[]
        def verify(installed,expected):
            assert installed==project and expected==manifest
            assert source_tree_digest(project)==manifest['source_manifest_sha256'] and config_tree_digest(project)==manifest['config_sha256']
            checks.append(True);return verification
        def invoke():
            descriptor=os.open(approval,os.O_RDONLY|os.O_DIRECTORY)
            try:return release_and_continue_qualified(project,candidate,db,directory/'integration-releases',manifest,approval_path=approval,approval_fd=descriptor,owner_identity=(info.st_dev,info.st_ino),approval_sha256=sha(ticket),current_source_revision=revision,dependency_digest=lambda:dependency_manifest_digest(project),verify=verify)
            except subprocess.CalledProcessError as exc:
                (root/'worker.stdout').write_text(exc.stdout);(root/'worker.stderr').write_text(exc.stderr);raise
            finally:os.close(descriptor)
        from threading import Event, Lock
        from amphenol_retry_completion import RetryReleaseApproval, deliver_qualified_operator_retry
        from coordinator import Coordinator
        from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
        from coordinator_store import Store
        from host_server import OperatorAmphenolRecipeEnrollment

        coordinator = Coordinator.__new__(Coordinator)
        coordinator.stop = Event()
        coordinator.workspace_lock = Lock()
        coordinator.control_lock = Lock()
        coordinator_base = project / 'dev/wrapper-coder/tasks'
        coordinator.store = Store(coordinator_base, company_revision_resolver=revision)
        for name in ('scheduler.lock', 'supervision.lock'):
            (coordinator_base / name).touch(mode=0o600, exist_ok=False)
        original_outcome = settled['outcome']['outcome_id']
        with closing(SQLiteRepository(jobs_path, 'fixture-sheet')) as sender:
            delivered = ManualReceiptV1HostBridge(
                coordinator, lambda: sender, enabled=True,
            ).manual_drain(outcome_id=original_outcome)
            assert delivered['results'] == [{'outcome_id': original_outcome, 'disposition': 'ACCEPTED'}], delivered
        with coordinator.store.connect() as ledger:
            task = {'id': historical_task, 'status': 'PAUSED_ERROR', 'isolated_workspace': True,
                    'held_repair_key': 'fixture-repair', 'integration': {'work_order': 'acquiretm-listing-membership-v1'},
                    'repair_provenance': {'repair_key': 'fixture-repair', 'outcome_id': original_outcome,
                                          'company_id': company['Company ID'], 'source_revision': revision_value}}
            ledger.execute('INSERT INTO tasks VALUES (?,?)', (historical_task, json.dumps(task)))
            ledger.execute('INSERT INTO inference_receipts VALUES (?,?,?,?)',
                           (inference_id, historical_task, 'COMPLETED', json.dumps(historical_receipt)))
        journal_path = directory / 'integration-release-journal.json'
        assert not journal_path.exists() and not (directory / 'next-scan.json').exists()
        assert sha(project / TARGET) != sha(candidate / TARGET)

        from contextlib import contextmanager
        import fcntl
        from amphenol_operator_one_shot import run_operator_release

        calls = []
        @contextmanager
        def fixture_maintenance_scope():
            calls.append('enter')
            try:
                yield
            finally:
                calls.append('exit')

        configured_windows = []

        def recover(*, execute, admitted_window=False, request_sha256=_digest(request), receipt_sha256=sha(ticket),
                    outcome_id=original_outcome):
            selected = RetryReleaseApproval(
                manifest['release_id'], str(approval), info.st_dev, info.st_ino, receipt_sha256,
            )
            if admitted_window:
                from contextlib import ExitStack
                from quiet_fixture import build_window
                from controller import UNITS

                quiet_root = root / ('quiet-' + str(len(configured_windows) + 1))
                quiet_root.mkdir(mode=0o700)

                class ScopedPatch:
                    def __init__(self, stack):
                        self.stack = stack

                    def setattr(self, target, name, value):
                        self.stack.enter_context(patch.object(target, name, value))

                with ExitStack() as stack:
                    window, unit_fixture, proofs = build_window(
                        quiet_root, ScopedPatch(stack), manifest['release_id'], directory)
                    confirmed = window.run(
                        execute=execute, approval=selected, original_outcome=outcome_id,
                        request_sha256=request_sha256, historical_task_id=historical_task,
                    )
                assert proofs == ['enter', 'closed', 'restored', 'exit']
                assert unit_fixture.active == {UNITS[0]: True, UNITS[1]: False}
                assert not window.units.sentinel.exists()
                assert [cmd for cmd in unit_fixture.commands if cmd[0] == 'start'] == [('start', UNITS[0])]
                assert json.loads(window.journal.read_bytes())['phase'] == 'RESTORED'
                configured_windows.append(window.journal)
                return confirmed
            return run_operator_release(
                execute=execute, approval=selected, original_outcome=outcome_id,
                request_sha256=request_sha256, historical_task_id=historical_task,
                maintenance_scope=fixture_maintenance_scope,
            )

        assert recover(execute=False) == {'state': 'HELD_OPERATOR_EXECUTION_NOT_REQUESTED'}
        assert recover(execute=True, outcome_id=None) == {'state': 'HELD_OPERATOR_ONE_SHOT_INPUTS'}
        assert calls == []
        for name in ('scheduler.lock', 'supervision.lock'):
            with (coordinator_base / name).open('rb') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                assert recover(execute=True) == {'state': 'HELD_OPERATOR_COORDINATOR_BUSY'}
            # A failed second acquisition must leave the first lease available.
            with (coordinator_base / 'scheduler.lock').open('rb') as scheduler:
                fcntl.flock(scheduler, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert recover(execute=True) == {'state': 'HELD_OPERATOR_COORDINATOR_CONTROLS'}
        coordinator.store.set_queue_enabled(False)
        assert recover(execute=True, request_sha256='c' * 64) == {
            'state': 'HELD_OPERATOR_RETAINED_QUALIFICATION',
        }
        assert not journal_path.exists() and not (directory / 'next-scan.json').exists()
        # Only the previously settled provider observation and prompt projection are fixtures.
        # The current operator source reads, stored task/receipt, compiler and installer are real.
        with (patch('job_search_helper.operator_amphenol_fetch.load_operator_amphenol_partial', return_value=observation),
              patch('amphenol_recipe_choice_input.read_operator_owned_choice_input', return_value=prepared)):
            first = recover(execute=True, admitted_window=True)
        write(root / 'FIRST.json', first)
        assert first['state'] == 'OPERATOR_RELEASE_CONFIRMED', first
        assert first['coordinator']['attempt_id'] == first['release']['attempt_id']
        assert calls == ['enter', 'exit'] * 4
        activation = journal_path.read_bytes()
        assert json.loads(activation)['state'] == 'COMPLETE'
        receipt_path = directory / 'integration-releases' / manifest['release_id'] / 'receipt.json'
        original_release_receipt = receipt_path.read_bytes()
        installed_file = (project / TARGET).stat()
        install_identity = (installed_file.st_dev, installed_file.st_ino, installed_file.st_mtime_ns)
        assert sha(project / TARGET) == sha(candidate / TARGET)
        assert first['retry']['state']=='COMPLETE',first
        cycle_id=first['retry']['cycle_id'];outcome=first['retry']['outcome']
        assert outcome['identity']['failed_request_id']==request_id
        with closing(State(db,readonly=True)) as state,closing(SQLiteRepository(jobs_path,'fixture-sheet',readonly=True)) as jobs,closing(InventoryInbox(directory/'inventories.sqlite3','fixture-sheet',readonly=True)) as inbox:
            cycle=state.cycle(cycle_id);assert cycle['status']=='Complete' and set(cycle['companies'])=={company['Company ID']}
            assert repair_retry_has_confirmed_publication(inbox,jobs,cycle,company['Company ID'])
            assert state.cycle(original)==prior and jobs.matches('Scan Cycles',{'Cycle ID':original})[0][1]==mirror
            assert jobs.matches('Companies',{'Company ID':'COMP-OTHER'})[0][1]==saved_other and jobs.matches('Job History',{'Job Key':'other-existing'})[0][1]==saved_job
            local=[r['Job Key'] for r in jobs.read('Job History') if r['Company']==company['Company']]
        workbook=json.loads((directory/'workbook-after.json').read_bytes());remote=[r['Job Key'] for r in workbook['jobs'] if r['Company']==company['Company']]
        assert local==remote and len(local)==1 and workbook['batches']==1,(local,remote,workbook['batches'])
        before = snapshot(directory)
        second = recover(execute=True, admitted_window=True)
        assert second['state'] == first['state'] == 'OPERATOR_RELEASE_CONFIRMED'
        assert first['release']['state'] == 'REQUEST_WRITTEN'
        assert second['release']['state'] == 'REQUEST_ALREADY_ADMITTED'
        assert {key: value for key, value in second['release'].items() if key != 'state'} == {
            key: value for key, value in first['release'].items() if key != 'state'
        }
        assert second['retry'] == first['retry'] and second['coordinator'] == first['coordinator']
        assert snapshot(directory) == before
        after_file = (project / TARGET).stat()
        assert (after_file.st_dev, after_file.st_ino, after_file.st_mtime_ns) == install_identity
        assert journal_path.read_bytes() == activation and receipt_path.read_bytes() == original_release_receipt
        workers=[json.loads(s) for s in (directory/'workers.jsonl').read_text().splitlines()];assert len(workers)==2 and len({r['pid'] for r in workers})==2
        assert all(r['runtime']['release_id']==manifest['release_id'] for r in workers)
        assert not (directory/'company-event-bridge').exists()
        assert (directory/'operator-company-requests/receipts').is_dir()
        owner = RetryReleaseApproval(manifest['release_id'], str(approval), info.st_dev, info.st_ino, sha(ticket))
        enrollment = OperatorAmphenolRecipeEnrollment(request_id, revision_value, request_sha256=_digest(request))
        def complete_terminal():
            return deliver_qualified_operator_retry(
                enrollment, coordinator, original_outcome=original_outcome, approval=owner,
            )

        terminal = complete_terminal()
        write(root / 'TERMINAL.json', terminal)
        assert terminal == {
            'state': 'RECIPE_RETRY_CONFIRMED',
            'attempt_id': first['release']['attempt_id'],
            'outcome_id': outcome['outcome_id'],
        }, terminal
        lifecycle = coordinator.store.retry_lifecycle(first['release']['attempt_id'])
        assert lifecycle['state'] == 'VALIDATED_COMPLETE' and len(lifecycle['events']) == 1
        assert lifecycle['events'][0]['record'] == outcome
        assert coordinator.store.all() == [task] and coordinator.store.unresolved_inferences() == []
        assert coordinator.store.inference_receipts(historical_task) == [historical_receipt]
        sender_before = snapshot(directory)
        with coordinator.store.connect() as ledger:
            receiver_before = list(ledger.iterdump())
        assert complete_terminal() == terminal and snapshot(directory) == sender_before
        with coordinator.store.connect() as ledger:
            assert list(ledger.iterdump()) == receiver_before
            assert ledger.execute('SELECT count(*) FROM scrape_outcome_delivery_receipts').fetchone() == (2,)
        assert len(configured_windows) == 2
        result={'result':'PASS_DISPOSABLE_BOUND_QUIET_WINDOW','restored_windows':len(configured_windows),'origin':'real_synthetic_operator_request','failed_request_id':request_id,'release_id':manifest['release_id'],'attempt_id':first['release']['attempt_id'],'cycle_id':cycle_id,'outcome_id':outcome['outcome_id'],'jobs':len(local),'fixture_batches':workbook['batches'],'provider_fixture_calls':1,'workbook_fixture_calls':1,'measured_workers':len(workers),'original_cycle_unchanged':True,'activation_receipt_and_file_identity_unchanged':True,'unrelated_rows_unchanged':True,'native_qualification':False,'host_completion_exercised':True,'coordinator_lifecycle':lifecycle['state'],'matching_receipts':2,'duplicate_effects_on_replay':False,'company_event_route_used':False,'source_pins':PINS}
        write(root/'RESULT.json',result);print(json.dumps(result,sort_keys=True),flush=True)
    except Exception as exc:
        write(root/'FAILURE.json',{'type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc(),'native_qualification':False})
        raise
if __name__=='__main__':main()

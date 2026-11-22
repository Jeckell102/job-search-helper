"""The retry reader requires the actual stored publication proof before delivery."""

from contextlib import contextmanager
from types import SimpleNamespace

import read_embraer_retry_completion as reader


def test_read_requires_the_matching_completed_cycle_and_publication(monkeypatch, tmp_path):
    enrollment = SimpleNamespace(request_id='operator-embraer-fixture', source_revision='own-revision',
                                 qualified=lambda record: record['outcome_id'] == 'original')
    release_id, attempt_id = 'current-release', 'exact-attempt'
    binding = {'company_id':'COMP-0634', 'failed_request_id':enrollment.request_id,
               'source_revision':enrollment.source_revision, 'attempt_id':attempt_id,
               'release':{'release_id':release_id}}
    request_id = 'company-retry:' + attempt_id
    original = {'outcome_id':'original'}
    terminal = {'outcome_id':'retry', 'outcome':'COMPLETE',
                'identity':{'request_id':request_id, 'attempt_id':attempt_id, 'cycle_id':'exact-cycle',
                            'company_id':'COMP-0634', 'failed_request_id':enrollment.request_id,
                            'source_revision':enrollment.source_revision, 'release_version':release_id,
                            'release_binding_sha256':'qualified-release-binding'}}
    origin_proof = (original, 'original-digest', False, True, None)
    retry_proof = (terminal, 'retry-digest', False, False, None)

    @contextmanager
    def open_approval():
        yield 'approved-owner'

    approval = SimpleNamespace(release_id=release_id, receipt_sha256='approval-digest', open=open_approval)
    cycle = {'id':'exact-cycle', 'status':'Complete', 'start_request_id':request_id,
             'request_fingerprint':'exact-request-fingerprint', 'repair_retry':binding,
             'companies':{'COMP-0634':{'stage':'complete'}}}
    connection = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [('retry',)]))
    repository = SimpleNamespace(db=connection, close=lambda: None,
                                 _outcome_delivery_rows=lambda consumer, outcome_id: [(outcome_id,)])
    state = SimpleNamespace(close=lambda:None, cycle=lambda _cycle_id:cycle, cycles=lambda:[cycle])
    inbox = SimpleNamespace(close=lambda:None)
    monkeypatch.setattr(reader,'assert_release_settled',lambda root:{'state':'COMPLETE','release_id':release_id,
                                                                    'record':str(tmp_path/'fixture-record')})
    monkeypatch.setattr(reader,'_read_json',lambda path:{})
    monkeypatch.setattr(reader,'_retry_binding',lambda receipt: binding)
    monkeypatch.setattr(reader,'canonical_retry_binding',lambda value: value)
    monkeypatch.setattr(reader,'_require_qualified_retry',lambda *args:None)
    monkeypatch.setattr(reader,'release_binding_sha256',lambda release:'qualified-release-binding')
    monkeypatch.setattr(reader,'SQLiteRepository',lambda *args,**kwargs:repository)
    monkeypatch.setattr(reader,'State',lambda *args,**kwargs:state)
    monkeypatch.setattr(reader,'InventoryInbox',lambda *args,**kwargs:inbox)
    monkeypatch.setattr(reader,'OutcomeDelivery',lambda *args:SimpleNamespace(
        _preflight=lambda row: origin_proof if row==('original',) else retry_proof))
    monkeypatch.setattr(reader,'superseded_cycle_ids',lambda cycles:set())
    monkeypatch.setattr(reader,'require_current_repair_retry',lambda *args:None)
    monkeypatch.setattr(reader,'_successful_inventory',lambda company:True)
    monkeypatch.setattr(reader,'repair_retry_has_confirmed_publication',lambda *args:True)
    arguments = dict(root=tmp_path, jobs=tmp_path/'jobs.sqlite3', destination='fixture', original_outcome='original')
    result = reader.read_embraer_retry_completion(enrollment, approval, **arguments)
    assert result['record'] == terminal and result['readback'] == retry_proof
    assert result['origin'] == origin_proof and result['sender_row'] == ('retry',)
    monkeypatch.setattr(reader,'repair_retry_has_confirmed_publication',lambda *args:False)
    assert reader.read_embraer_retry_completion(enrollment, approval, **arguments) is None

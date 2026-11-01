import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_search_helper.evidence_archives import EvidenceArchives, ArchiveRepository, save_registry, TAB, ROW_STRIDE
from job_search_helper.repository import MemoryRepository, RepositoryError, UncertainWriteError, SCHEMAS


def evidence(key='job', text='Full original description'):
    return {'tab': TAB, 'identity': {'Job Key': key, 'Source Hash': 'hash-'+key},
            'values': {'Job Description': text}, 'append_if_missing': True}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'archives.json'
        self.main = MemoryRepository()
        self.main.spreadsheet_id = 'master'
        self.children = {'archive1': MemoryRepository({TAB: []})}
        self.registry = {'version': 1, 'spreadsheet_id': 'master', 'archives': [
            {'spreadsheet_id': 'archive1', 'url': 'url1', 'reserved_bytes': 0}]}
        save_registry(self.path, self.registry)
        self.repo = EvidenceArchives(self.main, self.path, factory=self.children.__getitem__)

    def test_routes_evidence_and_keeps_history_and_decisions_in_master(self):
        history={'tab':'Job History','identity':{'Job Key':'job'},
                 'values':{'Added to Opportunities?':'Yes'},'append_if_missing':True}
        self.repo.commit([history,evidence()])
        self.assertEqual(self.main._sheets[TAB].records(),[])
        self.assertEqual(self.main.read('Job History')[0]['Added to Opportunities?'],'Yes')
        self.assertEqual(self.repo.read(TAB)[0]['Job Description'],'Full original description')
        self.assertIn(TAB,self.repo._committed_rows)
        self.assertIn('Job History',self.repo._committed_rows)

    def test_evidence_failure_cannot_commit_history(self):
        with patch.object(self.children['archive1'],'commit',side_effect=UncertainWriteError('lost')):
            with self.assertRaises(UncertainWriteError):
                self.repo.commit([evidence(), {'tab':'Job History','identity':{'Job Key':'job'},
                                              'append_if_missing':True}])
        self.assertEqual(self.main.read('Job History'),[])
        self.assertEqual(self.repo._committed_rows,{})

    def test_main_failure_replay_does_not_duplicate_evidence(self):
        ops=[evidence(),{'tab':'Job History','identity':{'Job Key':'job'},'append_if_missing':True}]
        with patch.object(self.main,'commit',side_effect=UncertainWriteError('lost')):
            with self.assertRaises(UncertainWriteError):self.repo.commit(ops)
        self.repo.commit(ops)
        self.assertEqual(len(self.repo.read(TAB)),1)
        self.assertEqual(len(self.main.read('Job History')),1)

    def test_uncertain_evidence_write_that_landed_replays_by_identity(self):
        original=self.children['archive1'].commit
        def lost(ops):original(ops);raise UncertainWriteError('lost response')
        with patch.object(self.children['archive1'],'commit',side_effect=lost):
            with self.assertRaises(UncertainWriteError):self.repo.commit([evidence()])
        self.repo.commit([evidence()])
        self.assertEqual(len(self.repo.read(TAB)),1)

    def test_readers_reload_volumes_and_resolve_stable_row_locators(self):
        self.children['archive2']=MemoryRepository({TAB:[{'Job Key':'second','Source Hash':'h','Job Description':'full'}]})
        self.registry['archives'].append({'spreadsheet_id':'archive2','url':'url2','reserved_bytes':100})
        save_registry(self.path,self.registry)
        rows=self.repo.read_columns(TAB,['Job Key'])
        self.assertEqual(rows[0][0],ROW_STRIDE+2)
        self.assertEqual(self.repo.read_row(TAB,rows[0][0])['Job Description'],'full')
        self.assertEqual(self.repo.read_many([TAB,'Job History'])[TAB][0]['Job Key'],'second')

    def test_rollover_new_identity_but_existing_updates_stay_in_original_volume(self):
        self.children['archive1'].commit([evidence()])
        self.registry['archives'][0]['reserved_bytes']=30_000_000
        save_registry(self.path,self.registry)
        def create():
            self.children['archive2']=MemoryRepository()
            item={'spreadsheet_id':'archive2','url':'url2','reserved_bytes':0}
            self.repo.registry['archives'].append(item)
            save_registry(self.path,self.repo.registry)
            return item
        with patch.object(self.repo,'_new_volume',side_effect=create) as new:
            self.repo.commit([evidence(),evidence('new'),evidence('new')])
        self.assertEqual(new.call_count,1)
        self.assertEqual(len(self.children['archive1'].read(TAB)),1)
        self.assertEqual(len(self.children['archive2'].read(TAB)),1)

    def test_missing_or_wrong_registry_fails_closed(self):
        self.path.unlink()
        with self.assertRaises(RepositoryError):self.repo.read(TAB)
        self.registry['spreadsheet_id']='different'
        save_registry(self.path,self.registry)
        with self.assertRaises(RepositoryError):self.repo.read(TAB)

    def test_duplicate_identity_blocks_write(self):
        self.children['archive1'].commit([evidence()])
        self.children['archive2']=MemoryRepository({TAB:self.children['archive1'].read(TAB)})
        self.registry['archives'].append({'spreadsheet_id':'archive2','url':'url2','reserved_bytes':0})
        save_registry(self.path,self.registry)
        with self.assertRaises(RepositoryError):self.repo.commit([evidence()])

    def test_does_not_change_callers_operations(self):
        self.repo.commit([evidence()]);ops=[evidence()];before=copy.deepcopy(ops)
        self.repo.commit(ops);self.assertEqual(ops,before)

    def test_google_existing_update_uses_targeted_reads_and_preserves_peer(self):
        from sheets_fixture import RangeSheets
        service=RangeSheets({TAB:[{'Job Key':'job','Source Hash':'hash-job','Job Description':'Original'},
                                 {'Job Key':'other','Source Hash':'hash-other','Job Description':'Peer text'}]})
        repo=ArchiveRepository(service,'archive1',schemas={TAB:SCHEMAS[TAB]},min_request_interval=0)
        op=evidence(text='Original');op['append_if_missing']=False
        result=repo.commit([op])
        ranges=[r for call in service.get_calls for r in call.get('ranges',[])]
        self.assertNotIn("'Job Evidence'!A1:Z1000",ranges)
        self.assertTrue(any('G2' in r for r in ranges))
        self.assertEqual(repo.read_row(TAB,3)['Job Description'],'Peer text')

    def test_archive_relocation_does_not_change_review_queues(self):
        from test_review_queue import ReviewQueueTests
        from job_search_helper.review_queue import build_review_queues
        original=ReviewQueueTests().make_repo()
        expected=build_review_queues(original)
        evidence_rows=original.read(TAB)
        self.children['archive1']=MemoryRepository({TAB:evidence_rows})
        original.spreadsheet_id='master'
        routed=EvidenceArchives(original,self.path,factory=self.children.__getitem__)
        actual=build_review_queues(routed)
        self.assertEqual(actual,expected)

    def test_pending_directory_update_is_retried_before_evidence_write(self):
        self.registry['directory_pending']=True;save_registry(self.path,self.registry)
        with patch.object(self.repo,'update_directory',side_effect=RepositoryError('directory failed')):
            with self.assertRaises(RepositoryError):self.repo.commit([evidence()])
        self.assertEqual(self.children['archive1'].read(TAB),[])


if __name__=='__main__':unittest.main()

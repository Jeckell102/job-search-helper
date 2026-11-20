"""One-sided Sheet ratings reconcile; concurrent or uncertain ratings remain held."""
import json
from pathlib import Path
import tempfile
import unittest
from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository


class OpportunityFitSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.local = SQLiteRepository(Path(self.temp.name)/'jobs.sqlite3','fixture',initialize=True)
        self.addCleanup(self.local.close)
        self.remote = MemoryRepository({'Opportunities':[{'Company':'Fixture','Job Title':'Engineer','Job URL':'https://example.com/job',
            'Fit Review':'Potential Fit','Last Checked':'2026-11-09'}]})
        self.remote.spreadsheet_id='fixture'
        for tab in SCHEMAS: self.local.import_rows(tab,enumerate(self.remote.read(tab),2))
        self.sync = SheetsSynchronizer(self.local,self.remote)
        self.rid=self.local.matches('Opportunities',{'Company':'Fixture','Job URL':'https://example.com/job'})[0][0]

    def edit(self,repo,**values):
        repo.commit([{'tab':'Opportunities','identity':{'Company':'Fixture','Job URL':'https://example.com/job'},'values':values}])

    def test_remote_rating_is_preserved_while_pending_date_can_publish(self):
        self.edit(self.local,**{'Last Checked':'2026-11-16'})
        self.edit(self.remote,**{'Fit Review':'Strong Potential Fit'})
        self.sync.pull()
        self.assertEqual(self.local.row('Opportunities',self.rid)['Fit Review'],'Strong Potential Fit')
        self.assertEqual(self.local.status()['conflicts'],0)
        self.sync.publish_batch()
        self.assertEqual(self.local.status()['pending_cells'],0)
        self.assertEqual(self.remote.read('Opportunities')[0]['Fit Review'],'Strong Potential Fit')
        self.assertEqual(self.remote.read('Opportunities')[0]['Last Checked'],'2026-11-16')

    def test_concurrent_local_rating_is_not_overwritten(self):
        self.edit(self.local,**{'Fit Review':'Not Relevant'})
        self.edit(self.remote,**{'Fit Review':'Strong Potential Fit'})
        self.sync.pull()
        self.assertEqual(self.local.row('Opportunities',self.rid)['Fit Review'],'Not Relevant')
        self.assertEqual(self.local.status()['conflicts'],1)

    def test_uncertain_prior_delivery_is_not_reinterpreted_as_one_sided_edit(self):
        with self.local.transaction():
            self.local.db.execute('INSERT INTO delivery_attempts VALUES (?,?,?)',
                ('Opportunities',self.rid,json.dumps({'Fit Review':'Not Relevant'})))
        self.edit(self.remote,**{'Fit Review':'Strong Potential Fit'})
        self.sync.pull()
        self.assertEqual(self.local.row('Opportunities',self.rid)['Fit Review'],'Potential Fit')
        self.assertEqual(self.local.status()['conflicts'],1)

    def test_unrecognized_rating_stays_a_conflict(self):
        self.edit(self.remote,**{'Fit Review':'unknown'})
        self.sync.pull()
        self.assertEqual(self.local.status()['conflicts'],1)

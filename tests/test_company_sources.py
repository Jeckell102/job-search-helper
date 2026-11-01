import unittest
from unittest.mock import patch
from job_search_helper.company_sources import REPAIRS,repair_source
from job_search_helper.ats import fetch_inventory,Inventory
from job_search_helper.browser_scraper import with_browser_fallback
class SourceRepairs(unittest.TestCase):
 def test_empty_source_resolves_only_exact_company(self):
  cid='COMP-0143';e=REPAIRS[cid];ats,url,note=repair_source('Browser','',cid,e['company']);self.assertEqual(url,e['url']);self.assertTrue(note)
  self.assertEqual(repair_source('Browser','','another-id',e['company']),('Browser','',''))
  self.assertEqual(repair_source('Browser','',cid,'Other Company'),('Browser','',''))
 def test_user_changed_source_wins(self):
  e=REPAIRS['COMP-0143'];self.assertEqual(repair_source('Browser','https://new.example/jobs','COMP-0143',e['company']),('Browser','https://new.example/jobs',''))
 def test_direct_fetcher_routes_repaired_url(self):
  e=REPAIRS['COMP-0143']
  with patch('job_search_helper.shared_boards.fetch_shared',return_value=Inventory('complete',ats='Dayforce')) as f:
   r=fetch_inventory('Browser','','COMP-0143',e['company']);self.assertEqual(f.call_args.args[1],e['url']);self.assertIn('Verified company source repair',r.reason)
 def test_browser_uses_same_repaired_source(self):
  e=REPAIRS['COMP-0143']
  with patch('job_search_helper.shared_boards.fetch_shared_browser',return_value=Inventory('complete',ats='Dayforce')) as browser:
   seen=[]
   def fetch(*args):seen.append(args);return Inventory('blocked',ats='Dayforce')
   r=with_browser_fallback(fetch)('Browser','','COMP-0143',e['company']);self.assertEqual(seen[0][1],e['url']);self.assertEqual(browser.call_args.args[1],e['url']);self.assertEqual(r.status,'complete')

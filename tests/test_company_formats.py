import json
from pathlib import Path
import unittest
from job_search_helper import shared_boards as s
from test_shared_boards import Fake

class CompanyFormats(unittest.TestCase):
 def test_custom_jazz_domain_pinned(self):
  b=s.board_link('https://jobs.nearearth.aero/apply')
  self.assertEqual(b.name,'JazzHR')
  self.assertTrue(s.allowed(b,b.url))
  self.assertFalse(s.allowed(b,'https://other.example/apply'))
  with self.assertRaises(ValueError):s.board_link('https://jobs.nearearth.aero.evil.example/apply')
 def test_breezy_visible_description_identity(self):
  url='https://matrix-technologies-inc.breezy.hr/p/54e60264d41b-senior-client-solutions-manager'
  b=s.board_link('https://matrix-technologies-inc.breezy.hr/')
  e={'id':'54e60264d41b','url':url,'name':'Senior Client Solutions Manager','company':{'friendly_id':b.slug}}
  body=(Path(__file__).parent/'fixtures/shared/matrix-visible.html').read_text()
  row=s.posting(b,Fake({url:body}),e,'c','Matrix Technologies')
  self.assertIn('$150,000',row['description'])
  self.assertGreater(len(row['description']),1000)
  for bad in [body.replace('<h1>Senior Client Solutions Manager</h1>','<h1>Other Job</h1>'),body.replace('property="og:url"','property="other"')]:
   with self.assertRaises(s.FetchError):s.posting(b,Fake({url:bad}),e,'c','Matrix Technologies')

class StructuredFallback(unittest.TestCase):
 def test_partial_workday_not_merged_with_generic_links(self):
  from unittest.mock import patch
  from job_search_helper.ats import Inventory
  from job_search_helper.browser_scraper import with_browser_fallback
  original=Inventory('partial',jobs=[{'posting_id':'official-id'}],ats='Workday')
  with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
   result=with_browser_fallback(lambda *args:original)('Workday','https://a.wd1.myworkdayjobs.com/External','c','C')
   self.assertIs(result,original);browser.assert_not_called()

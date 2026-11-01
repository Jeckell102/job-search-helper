import io
import unittest
from unittest.mock import patch,MagicMock
from job_search_helper.ats import HTTPTransport,FetchError

class LargeGreenhouse(unittest.TestCase):
 def transport(self,body):
  t=HTTPTransport(interval=0);r=MagicMock();r.__enter__.return_value=r;r.read.side_effect=io.BytesIO(body).read;r.status=200;r.headers={};t.opener.open=MagicMock(return_value=r);return t
 def test_full_board_gets_bounded_larger_allowance(self):
  with patch('job_search_helper.ats.MAX_RESPONSE_BYTES',8),patch('job_search_helper.ats.MAX_GREENHOUSE_BOARD_BYTES',32):
   t=self.transport(b'x'*20);self.assertEqual(len(t.get('https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true').body),20)
   with self.assertRaises(FetchError):self.transport(b'x'*33).get('https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true')
 def test_other_endpoints_keep_standard_bound(self):
  with patch('job_search_helper.ats.MAX_RESPONSE_BYTES',8),patch('job_search_helper.ats.MAX_GREENHOUSE_BOARD_BYTES',32):
   for url in ['https://api.lever.co/v0/postings/acme?mode=json','https://boards-api.greenhouse.io/v1/boards/acme/jobs/123','https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=false']:
    with self.subTest(url=url),self.assertRaises(FetchError):self.transport(b'x'*20).get(url)

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from job_search_helper.ats import FetchError
from job_search_helper.shared_boards import rippling_locations, posting, board_link

class RipplingLocationTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://ats.rippling.com/advanced-navigation/jobs/4b37654d-eca1-496b-9a7b-f9c39272164b'
        self.first = {'id':self.url.rsplit('/',1)[1], 'url':self.url, 'name':'Business Development Manager', 'locations':[{'name':'London, United Kingdom','workplaceType':'HYBRID'}]}
        self.second = copy.deepcopy(self.first)
        self.second['locations'][0]['name'] = 'Bristol, United Kingdom'

    def test_duplicate_locations_merge_only_with_matching_detail(self):
        e = rippling_locations([self.first,self.second])[0]
        self.assertEqual(len(e['locations']), 2)
        d = {'apiData':{'jobBoard':{'slug':'advanced-navigation'}, 'jobPost':{'uuid':e['id'],'name':e['name'],'url':self.url,'unlistedFromSearch':False,'description':{'role':'Job description'}}, 'workLocations':['London, United Kingdom','Bristol, United Kingdom']}}
        parser = type('Parsed', (), {'next':lambda self:d})()
        with patch('job_search_helper.shared_boards.checked', return_value=''), patch('job_search_helper.shared_boards.Scripts', return_value=parser):
            row = posting(board_link(self.url.rsplit('/',1)[0]), MagicMock(), e, 'C', 'Company')
            self.assertIn('London', row['location'])
            d['apiData']['workLocations'] = ['London, United Kingdom']
            with self.assertRaises(FetchError):
                posting(board_link(self.url.rsplit('/',1)[0]), MagicMock(), e, 'C', 'Company')

    def test_conflicting_or_ambiguous_duplicates_stay_partial(self):
        for change in ('metadata','repeat','missing'):
            second = copy.deepcopy(self.second)
            if change == 'metadata': second['name'] = 'Different'
            if change == 'repeat': second['locations'] = copy.deepcopy(self.first['locations'])
            if change == 'missing': second['locations'] = []
            with self.subTest(change=change), self.assertRaises(FetchError):
                rippling_locations([self.first,second])

    def test_captured_employer_listing_rows(self):
        path = Path(__file__).parent / 'fixtures/shared_boards/rippling-advanced-navigation-locations.json'
        rows = json.loads(path.read_text())
        merged = rippling_locations(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['_rippling_duplicate_locations'], [
            'Bristol, United Kingdom', 'London, United Kingdom', 'Newcastle upon Tyne, United Kingdom'])
        self.assertEqual({v['workplaceType'] for v in merged[0]['locations']}, {'REMOTE','ON_SITE'})

    def test_order_does_not_change_merged_record(self):
        self.assertEqual(rippling_locations([self.first,self.second]), rippling_locations([self.second,self.first]))

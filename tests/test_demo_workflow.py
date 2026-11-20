"""The advertised demo exercises managed review entirely with offline fixtures."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import cli


class OfflineDemoTests(unittest.TestCase):
    def test_demo_claims_reviews_and_creates_one_fixture_opportunity(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'demo'
            with patch('job_search_helper.runner._load_environment', side_effect=AssertionError('Demo must not load environment')), \
                    patch.object(cli, 'get_repository', side_effect=AssertionError('Demo must not open live repository')), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['demo', '--output', str(destination)]), 0)
            result = json.loads((destination / 'demo-results.json').read_text())
            self.assertEqual(result['before_review']['pending_reviews'], 1)
            self.assertEqual(result['after_review']['pending_reviews'], 0)
            self.assertEqual(len(result['tables']['Opportunities']), 1)
            self.assertEqual(result['tables']['Opportunities'][0]['Application Status'], 'Not Reviewed')
            self.assertEqual(len(result['tables']['Job History']), 1)
            self.assertEqual(result['tables']['Job History'][0]['Added to Opportunities?'], 'Yes')
            self.assertTrue((destination / 'review-queue/concurrent/review-runtime.sqlite3').exists())

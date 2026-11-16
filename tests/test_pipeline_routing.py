"""Public starts share orchestration; only the internal worker runs the scan."""
import unittest
from unittest.mock import patch
from job_search_helper import runner, launcher


class PipelineRoutingTests(unittest.TestCase):
    def test_both_public_entrypoints_start_the_pipeline_and_preserve_options(self):
        for entry in (runner.main, launcher.main):
            with patch('job_search_helper.scrape_first_pass.main', return_value=7) as workflow, \
                 patch.object(runner, 'scrape_main') as scan:
                self.assertEqual(entry(['start','--fetch-workers','15']),7)
                workflow.assert_called_once_with(['run','--scraper-args','--fetch-workers','15'])
                scan.assert_not_called()

    def test_resume_alias_routes_to_the_same_pipeline(self):
        with patch('job_search_helper.scrape_first_pass.main',return_value=0) as workflow:
            launcher.main(['resume','--fetch-workers','15'])
            workflow.assert_called_once_with(['run','--scraper-args','--resume','--fetch-workers','15'])

    def test_help_and_maintenance_do_not_launch_ai(self):
        for args in (['start','--help'],['storage','status'],['sync'],['preflight']):
            with patch.object(runner,'scrape_main',return_value=0) as scan, \
                 patch('job_search_helper.scrape_first_pass.main') as workflow:
                self.assertEqual(runner.main(args),0)
                scan.assert_called_once_with(args); workflow.assert_not_called()

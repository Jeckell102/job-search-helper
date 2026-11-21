import importlib.util
from pathlib import Path
import unittest


BASELINE = Path('/tmp/jsh-s5-acquiretm-membership-repair.20261121')
SOURCE = BASELINE / 'src/job_search_helper/acquiretm.py'
HISTORICAL_W1 = Path('/tmp/jsh-s5-amphenol-typed-live/result.json')
RECIPE = Path(__file__).with_name('acquiretm_membership_recipe.py')


def recipe():
    spec = importlib.util.spec_from_file_location('acquiretm_recipe', RECIPE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_w1():
    return {
        'page': 2, 'advertised_total': 42, 'first_page_count': 26,
        'refreshed_page_count': 16,
        'first_page_ids_sha256': '1' * 64,
        'premature_page_ids_sha256': '1' * 64,
        'refreshed_page_ids_sha256': '2' * 64,
        'premature_elapsed_ms': 121, 'refreshed_elapsed_ms': 563,
    }


class CurrentOwnedRecipeTests(unittest.TestCase):
    def test_archival_build_and_pin_are_byte_identical(self):
        module = recipe()
        result = module.build(SOURCE.read_bytes(), module.SELECTION, HISTORICAL_W1.read_bytes())
        self.assertEqual(result['receipt']['output_sha256'],
                         '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d')
        self.assertEqual(result['receipt']['witness_sha256'], module.WITNESS_SHA256)
        self.assertEqual(module.build.__name__, 'build')

    def test_current_owned_w1_changes_receipt_not_fixed_transform(self):
        module = recipe()
        source, witness = SOURCE.read_bytes(), current_w1()
        from job_search_helper.temporary_retry import _selected_sha
        binding = {'witness_sha256': _selected_sha(witness)}
        archival = module.build(source, module.SELECTION, HISTORICAL_W1.read_bytes())
        current = module.build_current_owned(source, module.SELECTION,
                                             'https://amphenol-aerospace.acquiretm.com/home.aspx', witness, binding)
        self.assertEqual((current['source'], current['diff']), (archival['source'], archival['diff']))
        self.assertEqual(current['receipt']['output_sha256'], archival['receipt']['output_sha256'])
        self.assertEqual(current['receipt']['witness_sha256'], binding['witness_sha256'])
        self.assertNotEqual(current['receipt']['witness_sha256'], module.WITNESS_SHA256)
        self.assertEqual(current['receipt']['selected_evidence'], module.SELECTION)

    def test_unknown_strategy_scope_and_invalid_transition_fail_closed(self):
        module = recipe()
        source, witness = SOURCE.read_bytes(), current_w1()
        from job_search_helper.temporary_retry import _selected_sha
        binding = {'witness_sha256': _selected_sha(witness)}
        with self.assertRaises(ValueError):
            module.build_current_owned(source, {'strategy': 'html_change', 'evidence': 'W1'},
                                       'https://amphenol-aerospace.acquiretm.com/home.aspx', witness, binding)
        with self.assertRaises(ValueError):
            module.build_current_owned(source, module.SELECTION, 'https://example.invalid/', witness, binding)
        wrong = dict(binding, witness_sha256='0' * 64)
        with self.assertRaises(ValueError):
            module.build_current_owned(source, module.SELECTION,
                                       'https://amphenol-aerospace.acquiretm.com/home.aspx', witness, wrong)
        malformed = {**witness, 'refreshed_elapsed_ms': 10**6}
        malformed_binding = {'witness_sha256': _selected_sha(malformed)}
        with self.assertRaises(ValueError):
            module.build_current_owned(source, module.SELECTION,
                                       module.W1['source'], malformed, malformed_binding)


if __name__ == '__main__':
    unittest.main()

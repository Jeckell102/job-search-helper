import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / 'jetson' / 'wrapper_commands.py'
SPEC = importlib.util.spec_from_file_location('wrapper_commands_under_test', PATH)
wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wrapper)


class WrapperCommandTests(unittest.TestCase):
    def test_campaign_controls_need_no_model_or_arguments(self):
        for action in ('autopilot-start', 'autopilot-status', 'autopilot-stop'):
            self.assertEqual(wrapper.parse_command('/wrapper ' + action), {'action': action})
            with self.assertRaises(ValueError):
                wrapper.parse_command('/wrapper ' + action + ' extra')

    def test_help_explains_single_jetson_lane(self):
        self.assertIn('/wrapper autopilot-start', wrapper.HELP)
        self.assertIn('one Jetson inference slot', wrapper.HELP)


if __name__ == '__main__':
    unittest.main()

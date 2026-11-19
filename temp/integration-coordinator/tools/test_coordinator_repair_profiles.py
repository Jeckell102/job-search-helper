"""M4 profile selection is deterministic and cannot start a worker."""
import unittest

from coordinator_repair_profiles import select_profile


def held(**changes):
    outcome = {
        'outcome': 'QUALIFIED_INTEGRATION_REPAIR',
        'repair_category': 'adapter_regression',
        'identity': {'company_id': 'COMP-0001', 'source_revision': 'rev-1',
                     'provider': 'greenhouse', 'adapter_version': 'adapter-1'},
    }
    outcome.update(changes)
    return {'repair_key': 'a' * 64, 'outcome': outcome}


def company(**changes):
    value = {'company_id': 'COMP-0001', 'source_revision': 'rev-1',
             'company': 'Acme', 'official_careers_url': 'https://jobs.example.test/acme'}
    value.update(changes)
    return value


def profile(**changes):
    value = {'profile_id': 'acme-greenhouse-v1', 'company_id': 'COMP-0001',
             'provider': 'greenhouse', 'adapter_version': 'adapter-1',
             'failure_category': 'adapter_regression',
             'configured_url': 'https://jobs.example.test/acme',
             'tests': ['tests/test_a.py'], 'source_targets': ['src/a.py'],
             'max_sessions': 2}
    value.update(changes)
    return value


class RepairProfileTests(unittest.TestCase):
    def test_exact_profile_produces_a_bounded_paused_task_assignment(self):
        assignment = select_profile(held(), company(), profiles=(profile(),))
        self.assertEqual(assignment['profile_id'], 'acme-greenhouse-v1')
        self.assertEqual(assignment['source_revision'], 'rev-1')
        self.assertEqual(assignment['integration']['company_id'], 'COMP-0001')
        self.assertEqual(assignment['integration']['tests'], ['tests/test_a.py'])
        self.assertNotIn('release', assignment['objective'].casefold().replace('do not release', ''))

    def test_mismatch_or_ambiguous_profile_never_produces_an_assignment(self):
        cases = (
            (held(), company(source_revision='rev-new'), (profile(),)),
            (held(repair_category='pagination_regression'), company(), (profile(),)),
            (held(), company(), (profile(provider='other'),)),
            (held(), company(), (profile(), profile(profile_id='second-profile'))),
            (held(), company(), ()),
        )
        for item, current, profiles in cases:
            with self.subTest(item=item, current=current, profiles=profiles):
                self.assertIsNone(select_profile(item, current, profiles=profiles))

    def test_malformed_profiles_fail_closed(self):
        self.assertIsNone(select_profile(held(), company(), profiles=(profile(source_targets=['../src/a.py']),)))
        self.assertIsNone(select_profile(held(), company(), profiles=(profile(tests=['tests/a.py']),)))


if __name__ == '__main__':
    unittest.main()

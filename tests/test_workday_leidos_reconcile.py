"""Stateful public-shape tests of Leidos's capped-board refresh branch."""
import copy
import json
import unittest
from job_search_helper.ats import HTTPResponse
from job_search_helper.workday import _fetch_leidos_partitions

HOST = 'leidos.wd5.myworkdayjobs.com'
SITE = 'External'
ENDPOINT = f'https://{HOST}/wday/cxs/leidos/{SITE}'
GROUPS = ('engineering', 'program-management')


def facets(counts):
    return [{'facetParameter': 'jobFamilyGroup', 'values': [
        {'id': group, 'count': count} for group, count in counts.items()]}]


def item(group, number, changed=False):
    return {'title': f'Leidos {group} {number}' + (' updated' if changed else ''),
            'externalPath': f'/job/US/{group}-{number}', 'locationsText': 'Remote',
            'bulletFields': [f'R-{group}-{number}']}


class RefreshTransport:
    def __init__(self, mode):
        self.mode = mode
        self.initial = {'engineering': [item('engineering', n) for n in range(1020)],
                        'program-management': [item('program-management', n) for n in range(1000)]}
        self.current = copy.deepcopy(self.initial)
        if mode != 'add_only':
            self.current['engineering'].pop(0)
        if mode == 'same_count':
            self.current['engineering'].append(item('engineering', 1020))
        elif mode not in ('remove_only', 'malformed_original'):
            self.current['program-management'].append(item('program-management', 1000))
        if mode == 'metadata':
            self.current['engineering'][0] = item('engineering', 1, changed=True)
        self.gets = []
        self.posts = []
        self.current_globals = 0
        self.malformed_sent = False

    @property
    def original_details_done(self):
        return len(self.gets) >= 2020

    def post(self, url, payload):
        self.posts.append(copy.deepcopy(payload))
        group = (payload.get('appliedFacets', {}).get('jobFamilyGroup') or [None])[0]
        cohort = self.current if self.original_details_done else self.initial
        malformed = (group == 'engineering' and self.mode == 'malformed_original'
                     and self.original_details_done and not self.malformed_sent)
        if malformed:
            # The real midnight failure retained a req-only card while the
            # original facet map was still visible to that page response.
            cohort = self.initial
        counts = {name: len(rows) for name, rows in cohort.items()}
        if group is None:
            if self.original_details_done:
                self.current_globals += 1
            body = {'total': 2000, 'jobPostings': [], 'facets': facets(counts)}
        else:
            offset = payload['offset']
            rows = copy.deepcopy(cohort[group][offset:offset + 20])
            if malformed:
                rows[0] = {'bulletFields': ['R-engineering-0']}
                self.malformed_sent = True
            if self.mode == 'continuous_drift' and self.current_globals >= 2 and offset == 0:
                rows[0]['title'] += ' moving again'
            if self.mode == 'duplicate_current' and self.current_globals >= 1 and offset == 20:
                rows[0] = copy.deepcopy(cohort[group][0])
            body = {'total': counts[group] if offset == 0 else 0,
                    'jobPostings': rows, 'facets': facets(counts) if offset == 0 else []}
        return HTTPResponse(200, json.dumps(body).encode(), {})

    def get(self, url):
        changed_phase = self.original_details_done
        self.gets.append(url)
        path = url[len(ENDPOINT):]
        listing = next((row for cohort in (self.current, self.initial)
                        for rows in cohort.values() for row in rows if row['externalPath'] == path), None)
        assert listing is not None, url
        if not changed_phase:
            listing = next(row for rows in self.initial.values() for row in rows if row['externalPath'] == path)
        new_job = path.endswith('/program-management-1000')
        if new_job and self.mode == 'blocked_refresh':
            return HTTPResponse(403, b'denied', {})
        ident = path.rsplit('/', 1)[-1]
        info = {'id': ident, 'title': listing['title'], 'jobReqId': listing['bulletFields'][0],
                'jobDescription': 'Full current public description.', 'jobPostingSiteId': SITE,
                'location': 'Remote', 'additionalLocations': [], 'posted': True}
        if new_job and self.mode == 'new_missing':
            info['jobDescription'] = ''
        if new_job and self.mode == 'duplicate_id':
            info['id'] = 'engineering-1'
        return HTTPResponse(200, json.dumps({'jobPostingInfo': info}).encode(), {})


class LeidosRefreshTests(unittest.TestCase):
    def run_case(self, mode):
        transport = RefreshTransport(mode)
        initial = {'total': 2000, 'jobPostings': [],
                   'facets': facets({g: len(v) for g, v in transport.initial.items()})}
        payload = {'appliedFacets': {}, 'limit': 20, 'offset': 0, 'searchText': ''}
        result = _fetch_leidos_partitions(ENDPOINT, payload, SITE, HOST, 'COMP-0003',
                                          'Leidos', transport, initial)
        return result, transport

    def assert_current(self, mode, fresh_requests):
        result, transport = self.run_case(mode)
        self.assertEqual(result.status, 'complete', result.reason)
        current = {row['externalPath']: row for rows in transport.current.values() for row in rows}
        self.assertEqual({row['url'][len(f'https://{HOST}/{SITE}'):]: row['title'] for row in result.jobs},
                         {path: row['title'] for path, row in current.items()})
        self.assertEqual(len(result.jobs), len(current))
        self.assertEqual(len(transport.gets), 2020 + fresh_requests)
        self.assertEqual(transport.current_globals, 3)
        self.assertIn('Reconciled once', result.reason)
        return result, transport

    def test_removal_reuses_all_remaining_descriptions_and_excludes_closed_job(self):
        result, _ = self.assert_current('remove_only', 0)
        self.assertEqual(len(result.jobs), 2019)

    def test_addition_fetches_only_new_description(self):
        self.assert_current('add_only', 1)

    def test_same_count_substitution_excludes_old_and_fetches_new(self):
        self.assert_current('same_count', 1)

    def test_remove_and_add_reuse_unchanged_descriptions(self):
        self.assert_current('remove_add', 1)

    def test_changed_metadata_forces_another_detail_fetch(self):
        result, transport = self.assert_current('metadata', 2)
        url = ENDPOINT + '/job/US/engineering-1'
        self.assertEqual(transport.gets.count(url), 2)
        self.assertTrue(any(row['title'].endswith('updated') for row in result.jobs))

    def test_original_malformed_final_card_can_reconcile_a_stable_current_cohort(self):
        _, transport = self.assert_current('malformed_original', 0)
        self.assertTrue(transport.malformed_sent)

    def test_second_cohort_drift_stays_partial_and_does_not_retry_again(self):
        result, transport = self.run_case('continuous_drift')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 2020)
        self.assertEqual(transport.current_globals, 2)

    def test_missing_new_description_retains_original_partial_jobs(self):
        result, transport = self.run_case('new_missing')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 2020)
        self.assertEqual(len(transport.gets), 2021)
        self.assertEqual(transport.current_globals, 2)

    def test_blocked_refresh_retains_original_jobs_and_stops(self):
        result, transport = self.run_case('blocked_refresh')
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(len(result.jobs), 2020)
        self.assertEqual(len(transport.gets), 2021)
        self.assertEqual(transport.current_globals, 2)

    def test_duplicate_current_paths_cannot_become_complete(self):
        result, transport = self.run_case('duplicate_current')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 2020)
        self.assertEqual(len(transport.gets), 2020)

    def test_duplicate_new_opaque_id_cannot_become_complete(self):
        result, _ = self.run_case('duplicate_id')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 2020)


if __name__ == '__main__':
    unittest.main()

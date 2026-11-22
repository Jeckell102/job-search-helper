from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from hashlib import sha256
from pathlib import Path
import os
from unittest import TestCase

import pytest

from job_search_helper.runner import _run_scan_with_retries
from test_acquiretm import PacedDispatch


BASE = Path('/tmp/jsh-fresh-amphenol-qualification.FdVVPAdT/candidate')
TARGET = Path('src/job_search_helper/acquiretm.py')


class FixtureEngine:
    def __init__(self, responses):
        self.dispatch = PacedDispatch(TestCase(), responses)
        self.state = self
        self.row = {}
        self.results = []

    def cycle(self, cycle_id):
        return {'companies': {'COMP-0490': self.row}}

    def resume_local(self, cycle_id, **options):
        result = self.dispatch.run()
        self.results.append(result)
        self.row['stage'] = result.status
        return {'attempted_company_ids': ['COMP-0490'], 'run_counts': {'new_jobs': 0}}


def test_candidate_source_vector_changes_only_one_module_and_listing_bytes_are_exact():
    current = Path.cwd() / os.environ.get('QA_CANDIDATE', 'candidate')
    def tree(base):
        return {p.relative_to(base).as_posix(): sha256(p.read_bytes()).hexdigest()
                for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    a, b = tree(BASE), tree(current)
    assert {p for p in a.keys() | b.keys() if a.get(p) != b.get(p)} == {TARGET.as_posix()}
    def listing(path):
        raw = path.read_bytes()
        return raw[raw.index(b'def parse_listing('):raw.index(b'class _DetailClient:')]
    assert listing(BASE / TARGET) == listing(current / TARGET)


@pytest.mark.parametrize('response', ((429, {'Retry-After': '0'}), (429, {'Retry-After': '3600'}),
    (503, {'Retry-After': format_datetime(datetime.now(timezone.utc) + timedelta(hours=1), usegmt=True)})))
def test_actual_normal_retry_loop_cannot_restart_a_provider_hold(response):
    engine = FixtureEngine([response])
    _run_scan_with_retries(engine, 'CYC-PRIVATE', partial_retries=1)
    [held] = engine.results
    assert held.status == 'blocked'
    assert 'Retry-After until' in held.reason
    assert engine.dispatch.events == [('listing', 0), ('detail', 0)]


@pytest.mark.parametrize('response', (TimeoutError(), (503, {'Retry-After': '5'})))
def test_exhausted_transient_attempt_keeps_pacing_across_normal_company_retry(response):
    engine = FixtureEngine([response] * 3)
    _run_scan_with_retries(engine, 'CYC-PRIVATE', partial_retries=1)
    assert [result.status for result in engine.results] == ['partial', 'complete']
    first, second, third = [stamp for tag, stamp in engine.dispatch.events[:4] if tag == 'detail']
    assert (first, second, third) == (0, 15, 30)
    last_attempt_end = 33
    assert engine.dispatch.events[4][0] == 'listing'
    listing_restart = engine.dispatch.events[4][1]
    print(f'third detail finished at {last_attempt_end}; next Company listing started at {listing_restart}')
    assert listing_restart - last_attempt_end >= 12

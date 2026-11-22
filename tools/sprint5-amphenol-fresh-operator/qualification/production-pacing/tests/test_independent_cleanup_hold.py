from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import pytest

from job_search_helper import acquiretm
from job_search_helper.ats import fetch_inventory
from job_search_helper.runner import _run_scan_with_retries
from test_acquiretm import PacedDispatch, SOURCE
from test_independent_cycle_spacing import FixtureEngine


@pytest.mark.parametrize('cleanup', ('browser-close', 'playwright-exit'))
def test_measured_429_stays_blocked_even_if_browser_cleanup_raises(cleanup):
    class Dispatch(PacedDispatch):
        runs = 0

        def run(self):
            self.runs += 1
            def close():
                if self.runs == 1 and cleanup == 'browser-close':
                    raise OSError('fixture browser shutdown failed')
            context = SimpleNamespace(new_page=lambda: self.page, request=self.request)
            browser = SimpleNamespace(new_context=lambda: context, close=close)
            engine = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))

            @contextmanager
            def playwright():
                try:
                    yield engine
                finally:
                    if self.runs == 1 and cleanup == 'playwright-exit':
                        raise OSError('fixture Playwright exit failed')

            with patch.object(acquiretm, '_DetailClient', self.make_client), patch(
                    'playwright.sync_api.sync_playwright', playwright):
                return fetch_inventory('AcquireTM', SOURCE, 'COMP-0490', 'Amphenol Aerospace')

    engine = FixtureEngine([])
    engine.dispatch = Dispatch(TestCase(), [(429, {'Retry-After': '3600'})])
    _run_scan_with_retries(engine, 'CYC-PRIVATE', partial_retries=1)
    statuses = [result.status for result in engine.results]
    print(f'{cleanup}: statuses {statuses}, fake requests {engine.dispatch.events}')
    assert statuses == ['blocked']
    assert 'Retry-After until' in engine.results[0].reason
    assert engine.dispatch.events == [('listing', 0), ('detail', 0)]

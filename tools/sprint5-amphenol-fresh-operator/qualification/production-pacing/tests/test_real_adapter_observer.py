from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest import TestCase
from unittest.mock import patch

import pytest

import confirm_recipe_candidate as evaluator
from job_search_helper import acquiretm, ats, integration_release
from test_acquiretm import PacedDispatch, detail, fetch_url

ROOT = Path('/tmp/jsh-amphenol-production-pacing.q7WLuQwO/candidate')
PREP_PIN = '7e0ca2034fc3be3003edce8bf77375ce0f6d74ce8754ab8822dd770b1378fa0c'


def evaluate_real(monkeypatch, replies, *, fast=False):
    fixture = PacedDispatch(TestCase(), replies)
    context = SimpleNamespace(new_page=lambda: fixture.page, request=fixture.request)
    browser = SimpleNamespace(new_context=lambda: context, close=lambda: None)
    process = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    original_init = acquiretm._DetailClient.__init__

    def client_init(instance, request):
        original_init(instance, request, clock=lambda: fixture.now, sleep=fixture.sleep)

    monkeypatch.setattr(acquiretm._DetailClient, '__init__', client_init)
    monkeypatch.setattr(evaluator.time, 'monotonic_ns', lambda: int(fixture.now * 1e9))
    if fast:
        monkeypatch.setattr(acquiretm._DetailClient, 'wait', lambda self: None)
    jobs = [(str(number), fetch_url(number), f'Engineer {number}') for number in (1, 2)]
    facts = []
    for ident, url, title in jobs:
        desc = ats.text(__import__('json').loads(detail({'id':ident,'url':url,'title':title}).split('>')[1].split('<')[0])['description'])
        facts.append({'id':ident,'url':url,'employer':'amphenol aerospace','description_chars':len(desc),
                      'description_sha256':hashlib.sha256(desc.encode()).hexdigest()})
    monkeypatch.setattr(evaluator,'COHORT_SHA256',evaluator.digest(jobs))
    monkeypatch.setattr(evaluator,'DETAILS_SHA256',evaluator.digest(facts))
    manifest = json.loads((ROOT.parent / "PROPOSED_MANIFEST.json").read_bytes())
    measured = []
    def private_dependency_measurement(project):
        assert project == ROOT
        measured.append(project)
        return manifest["dependency_manifest_sha256"]

    # This check executes the real private candidate config/source measurements
    # and the real dispatch; only shared installation dependency inventory is
    # replaced with the declaration so the fixture opens no production files.
    monkeypatch.setattr(evaluator, "PROJECT", ROOT, raising=False)
    monkeypatch.setattr(integration_release, "dependency_manifest_digest", private_dependency_measurement)
    records = []
    with patch('playwright.sync_api.sync_playwright', lambda: nullcontext(process)):
        try:
            code = evaluator.evaluate(ROOT, evaluator.prepare(ROOT, PREP_PIN), record=records.append)
        except RuntimeError as error:
            code = error
    if not isinstance(code, RuntimeError):
        assert measured == [ROOT, ROOT]
    return fixture, records, code


def test_actual_adapter_429_produces_terminal_hold(monkeypatch):
    fixture, rows, result = evaluate_real(monkeypatch, [(429, {'Retry-After':'3600'})])
    print('normal candidate events:', fixture.events, 'terminal:', repr(result))
    assert fixture.events == [('listing',0),('detail',0)]
    assert result == 1
    assert rows[-1]['stage'] == 'held_provider_rate_limit'
    assert rows[-1]['retry_after_seconds'] == 3600


def test_unpaced_success_cannot_be_accepted(monkeypatch):
    fixture, rows, result = evaluate_real(monkeypatch, [], fast=True)
    print('unpaced candidate events:', fixture.events, 'terminal:', repr(result))
    assert fixture.events == [('listing',0),('detail',0),('detail',3),('listing',6)]
    assert isinstance(result, RuntimeError)
    assert not any(r['stage']=='observation_candidate_confirmation_passed' for r in rows)


def test_actual_adapter_normal_pacing_and_full_verification(monkeypatch):
    fixture, rows, result = evaluate_real(monkeypatch, [])
    print('normal successful candidate events:', fixture.events, 'terminal:', repr(result))
    assert fixture.events == [('listing',0),('detail',0),('detail',15),('listing',30)]
    assert result == 0
    assert rows[-1]['stage'] == 'observation_candidate_confirmation_passed'
    assert rows[-1]['count'] == 2
    assert [row['page_count'] for row in rows if row['stage']=='listing_complete'] == [2,2]


def test_actual_adapter_long_503_produces_terminal_hold(monkeypatch):
    fixture, rows, result = evaluate_real(monkeypatch, [(503, {'Retry-After':'3600'})])
    print('normal long 503 candidate events:', fixture.events, 'terminal:', repr(result))
    assert fixture.events == [('listing',0),('detail',0)]
    assert result == 1
    assert rows[-1]['stage'] == 'held_provider_retry_after'
    assert rows[-1]['status'] == 503
    assert rows[-1]['retry_after_seconds'] == 3600

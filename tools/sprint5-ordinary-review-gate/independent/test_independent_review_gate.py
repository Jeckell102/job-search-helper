import stat
from types import SimpleNamespace

import pytest

from job_search_helper import pipeline_probe
from test_ordinary_verification_pending import attempt
from test_s5_ordinary_publication_continuation import measured_scope
from test_s5_ordinary_review_gate import CYCLE_ID, controller_for, publish
from test_s5_ordinary_worker_handoff import local_worker


def finish_exact_cycle(measured_scope, monkeypatch):
    launch, *_ = measured_scope
    named = publish(launch, monkeypatch, typed=False)
    assert launch(**named, finish_ordinary_verification=True) == 0


def test_exact_named_terminal_can_enter_review_using_real_saved_cycle(measured_scope, monkeypatch, tmp_path):
    finish_exact_cycle(measured_scope, monkeypatch)
    assert pipeline_probe.inspect_ordinary_review(CYCLE_ID)['state'] == 'TERMINAL'
    # The measured fixture keeps its parent scraper lease open for replay.
    # Simulate the already-completed named worker releasing it, and read real State.
    monkeypatch.setattr(pipeline_probe, 'locked', lambda path: False)
    info = pipeline_probe.inspect()
    controller = controller_for(info, pipeline_probe.inspect_ordinary_review)
    controller.project = tmp_path
    controller.args = SimpleNamespace(command='review', cycle=CYCLE_ID, resume=False)
    controller.helper = controller.preflight = lambda *args: pytest.fail('unexpected general storage action')
    called = []
    controller.ai_preflight = lambda: called.append('ai_preflight')
    controller.review = lambda: called.append('review')
    assert controller.run() == 0
    assert called == ['ai_preflight', 'review']


def test_exact_terminal_probe_preserves_database_permissions(measured_scope, monkeypatch):
    finish_exact_cycle(measured_scope, monkeypatch)
    _, state, jobs, inbox = measured_scope
    for path in (state, jobs, inbox):
        path.chmod(0o640)
    assert pipeline_probe.inspect_ordinary_review(CYCLE_ID)['state'] == 'TERMINAL'
    actual = tuple(stat.S_IMODE(path.stat().st_mode) for path in (state, jobs, inbox))
    assert actual == (0o640, 0o640, 0o640)

"""Exercise the real normal dispatcher using fixture-only public responses."""

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import qualify_embraer_normal_dispatch as q

ROOT = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0')
LISTING = tuple(
    {'id': number * 12, 'name': name, 'url': q.BOARD + 'p/' + number * 12 + '-' + name.lower(),
     'company': {'friendly_id': 'embraer'}}
    for number, name in (('1', 'One'), ('2', 'Two'))
)


def test_real_dispatch_matches_full_detail_and_omitted_row_holds(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'src'))
    from job_search_helper import ats
    from job_search_helper.integration_release import source_tree_digest

    source_tree = source_tree_digest(ROOT)

    class Transport:
        def get(self, url):
            if url == q.LISTING:
                return ats.HTTPResponse(200, json.dumps(LISTING).encode())
            expected = next(row for row in LISTING if row['url'] == url)
            job = {'@type': 'JobPosting', 'url': url, 'title': expected['name'],
                   'description': '<p>Complete responsibilities and qualifications.</p>'}
            raw = '<script type="application/ld+json">' + json.dumps(job) + '</script>'
            return ats.HTTPResponse(200, raw.encode(), {'Content-Type': 'text/html'})

    pins = {name: sha256((ROOT / 'src/job_search_helper' / (name + '.py')).read_bytes()).hexdigest()
            for name in ('ats', 'shared_boards')}
    call = ats.fetch_inventory
    report = q.qualify(ROOT, pins, source_tree, Transport())
    assert report['advertised_total'] == report['full_description_count'] == 2
    assert report['transport_call_count'] == 4

    def omitted(*args, **kwargs):
        result = call(*args, **kwargs)
        return SimpleNamespace(**{**result.__dict__, 'jobs': result.jobs[:-1]})

    monkeypatch.setattr(ats, 'fetch_inventory', omitted)
    with pytest.raises(ValueError, match='exactly cover'):
        q.qualify(ROOT, pins, source_tree, Transport())

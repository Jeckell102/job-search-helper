import json
import os
from pathlib import Path
import tempfile

import pytest

import exchange as implementation
from exchange import FixtureExchange, Hold


FIXTURES = implementation.LANE / 'fixtures'
EVIDENCE = b'independent fixture terminal receipt'


@pytest.fixture
def site():
    FIXTURES.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=FIXTURES) as name:
        root = Path(name)
        for subdir in ('checkouts', 'control'):
            (root / subdir).mkdir(mode=0o700)
        pairs = []
        for index in range(3):
            original = root / 'checkouts' / f'checkout {index}'
            sentinel = root / 'checkouts' / f'.exchange-park-{index}'
            original.mkdir(mode=0o700)
            (original / 'launcher').write_text(f'fixture {index}')
            sentinel.mkdir(mode=0o500)
            pairs.append((original, sentinel))
        yield FixtureExchange(root, pairs)


def states(site):
    return [(left / 'launcher').exists() for left, _ in site.pairs]


def journal(site):
    return json.loads((site.root / 'control' / implementation.JOURNAL).read_bytes())


def kill_after_swap(monkeypatch, operation):
    exchange = implementation.exchange

    def crash(*args):
        exchange(*args)
        os._exit(71)

    with monkeypatch.context() as patch:
        patch.setattr(implementation, 'exchange', crash)
        pid = os.fork()
        if pid == 0:
            try:
                operation()
            finally:
                os._exit(72)
        _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 71


def test_crash_after_swap_reconciles_exact_prefix(site, monkeypatch):
    originals = [original.stat().st_ino for original, _ in site.pairs]
    sentinels = [sentinel.stat().st_ino for _, sentinel in site.pairs]
    site.prepare()
    assert len(journal(site)['intent']['pairs']) == 3
    kill_after_swap(monkeypatch, site.close)
    assert states(site) == [False, True, True]
    assert journal(site)['completed'] == 0
    with pytest.raises(Hold):
        site.witness('closed')

    resumed = FixtureExchange(site.root, site.pairs)
    proof = resumed.close()
    assert resumed.close() == resumed.witness('closed') == proof
    assert [left.stat().st_ino for left, _ in site.pairs] == sentinels
    assert [right.stat().st_ino for _, right in site.pairs] == originals


@pytest.mark.parametrize('replace', ['absent', 'substitute', 'symlink'])
def test_changed_later_endpoint_blocks_first_swap(site, replace):
    site.prepare()
    _, slot = site.pairs[-1]
    slot.rename(slot.with_name('displaced'))
    if replace == 'substitute':
        slot.mkdir(mode=0o500)
    if replace == 'symlink':
        slot.symlink_to(slot.with_name('displaced'))
    with pytest.raises(Hold):
        site.close()
    assert states(site) == [True, True, True]
    assert journal(site)['completed'] == 0


@pytest.mark.parametrize('after_close', [False, True])
def test_occupied_pinned_sentinel_blocks_close_or_witness(site, after_close):
    site.prepare()
    if after_close:
        site.close()
    slot = site.pairs[-1][0 if after_close else 1]
    slot.chmod(0o700)
    (slot / 'unexpected').touch()
    slot.chmod(0o500)
    with pytest.raises(Hold, match='occupied'):
        site.witness('closed') if after_close else site.close()
    assert states(site) == [not after_close] * 3


def test_occupied_initial_sentinel_blocks_journal(site):
    _, slot = site.pairs[-1]
    slot.chmod(0o700)
    (slot / 'unexpected').touch()
    slot.chmod(0o500)
    with pytest.raises(Hold, match='sentinel'):
        site.prepare()
    assert not (site.root / 'control' / implementation.JOURNAL).exists()
    assert all(states(site))


def test_terminal_proof_and_interrupted_restore(site, monkeypatch):
    site.prepare()
    with pytest.raises(Hold, match='closure incomplete'):
        site.restore(EVIDENCE, verify_terminal=lambda *_: True)
    expected = site.close()
    with pytest.raises(Hold, match='external terminal proof'):
        site.restore(EVIDENCE, verify_terminal=lambda *_: False)
    assert site.witness('closed') == expected

    def external(proof, evidence):
        return proof == expected and evidence == EVIDENCE

    kill_after_swap(monkeypatch, lambda: site.restore(EVIDENCE, verify_terminal=external))
    assert states(site) == [True, False, False]
    assert journal(site)['phase'] == 'restoring' and journal(site)['completed'] == 0
    resumed = FixtureExchange(site.root, site.pairs)
    with pytest.raises(Hold, match='evidence changed'):
        resumed.restore(b'other receipt', verify_terminal=external)
    with pytest.raises(Hold, match='external terminal proof'):
        resumed.restore(EVIDENCE, verify_terminal=lambda *_: False)
    assert states(site) == [True, False, False]
    restored = resumed.restore(EVIDENCE, verify_terminal=external)
    assert restored == resumed.witness('restored')
    assert restored.generation == expected.generation and restored.intent_sha256 == expected.intent_sha256
    assert all(states(site))
    assert all(list(right.iterdir()) == [] for _, right in site.pairs)


def test_unjournaled_path_order_is_rejected(site):
    site.prepare()
    with site._open(write=True) as (parent, _, _pins):
        canonical, parked = site.pairs[1]
        implementation.exchange(parent, canonical.name, parent, parked.name)
    with pytest.raises(Hold, match='placements disagree'):
        site.close()
    assert states(site) == [True, False, True]


def test_refuses_outside_endpoint_and_symlinked_fixture_root(site):
    with pytest.raises(Hold, match='outside'):
        FixtureExchange(Path('/tmp'), site.pairs)
    with pytest.raises(Hold, match='outside'):
        FixtureExchange(site.root, [(site.root / 'elsewhere', site.pairs[0][1])])
    lookalike = FIXTURES / (site.root.name + '-alias')
    lookalike.symlink_to(site.root)
    try:
        alias_pairs = [(lookalike / left.relative_to(site.root), lookalike / right.relative_to(site.root))
                       for left, right in site.pairs]
        with pytest.raises(Hold, match='filesystem check failed'):
            FixtureExchange(lookalike, alias_pairs).prepare()
    finally:
        lookalike.unlink()


def test_crash_after_progress_replace_before_journal_sync(site, monkeypatch):
    site.prepare()
    replace = os.replace

    def crash(source, destination, **kwargs):
        replace(source, destination, **kwargs)
        if destination == implementation.JOURNAL:
            os._exit(73)

    with monkeypatch.context() as patch:
        patch.setattr(implementation.os, 'replace', crash)
        pid = os.fork()
        if pid == 0:
            try:
                site.close()
            finally:
                os._exit(74)
        _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 73
    assert states(site) == [False, True, True]
    assert journal(site)['completed'] == 1

    calls = []
    actual_sync, actual_exchange = os.fsync, implementation.exchange

    def sync(fd):
        if os.fstat(fd).st_ino == (site.root / 'control').stat().st_ino:
            calls.append('journal directory sync')
        actual_sync(fd)

    def swap(*args):
        assert calls[0] == 'journal directory sync'
        calls.append('swap')
        actual_exchange(*args)

    monkeypatch.setattr(implementation.os, 'fsync', sync)
    monkeypatch.setattr(implementation, 'exchange', swap)
    assert FixtureExchange(site.root, site.pairs).close() == site.witness('closed')
    assert calls.count('swap') == 2


def test_substituted_parent_with_same_endpoints_blocks_resume(site):
    site.prepare()
    parent = site.root / 'checkouts'
    original_parent = parent.rename(site.root / 'moved')
    parent.mkdir(mode=0o700)
    # Keep the sealed sentinel non-writable while moving the entire parent aside.
    # Put the actual endpoint inodes at the expected names under the substitute.
    for left, right in site.pairs:
        (original_parent / left.name).rename(left)
        parked = original_parent / right.name
        parked.chmod(0o700)
        parked.rename(right)
        right.chmod(0o500)
    with pytest.raises(Hold, match='journal does not match pinned fixture'):
        site.close()
    assert all(states(site))


def test_read_only_witness_does_not_create_or_replace_controls(site):
    control = site.root / 'control'
    with pytest.raises(Hold):
        site.witness('closed')
    assert list(control.iterdir()) == []
    site.prepare()
    assert site.close() is not None
    before = {path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
              for path in control.iterdir()}
    assert site.witness('closed').phase == 'closed'
    after = {path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
             for path in control.iterdir()}
    assert before == after

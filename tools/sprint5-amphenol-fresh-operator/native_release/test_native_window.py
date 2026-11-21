"""Disposable filesystem composition; all service/observer/app boundaries substituted."""
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import native_window as n


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


X = load('window_fixture_exchange', Path(__file__).parent / 'vendor/host_exchange.py')


class Files:
    @staticmethod
    def write(path, data, mode=0o600, replace=False):
        if path.exists() and not replace:
            raise ValueError('already exists')
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_bytes(data)
        temporary.chmod(mode)
        os.replace(temporary, path)

    @staticmethod
    def ensure_file(path, data, mode=0o600):
        if path.exists():
            Files.check_file(path, data, mode)
        else:
            Files.write(path, data, mode)

    @staticmethod
    def check_file(path, data, mode):
        assert path.read_bytes() == data and path.stat().st_mode & 0o777 == mode

    @staticmethod
    def sync_unlink(path):
        path.unlink()

    @staticmethod
    def ref(path):
        st = path.stat()
        return [st.st_dev, st.st_ino, st.st_mode & 0o777, st.st_uid, st.st_gid,
                sha256(path.read_bytes()).hexdigest()]

    @staticmethod
    @contextmanager
    def lock(path):
        with open(path, 'r+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield stream.fileno()

    read_object = staticmethod(lambda path: json.loads(path.read_bytes()))
    gate = SimpleNamespace(syncdir=lambda path: None)


class FakeSystemd:
    PROPERTIES = ('Id', 'LoadState', 'ActiveState', 'SubState', 'UnitFileState', 'MainPID',
        'ControlPID', 'ControlGroup', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload')
    shared = None

    def __init__(self, exe, directory, sentinel):
        self.exe, self.directory, self.sentinel = exe, directory, sentinel
        self.data = f'[Unit]\nConditionPathExists=!{sentinel}\n'.encode()

    @property
    def s(self):
        return type(self).shared

    def command(self, op, *args, **kwargs):
        self.s['commands'].append((op, args))
        if op == 'daemon-reload': return ''
        if op == 'show':
            if args and args[0] == n.TIMER:
                return 'inactive' if 'ActiveState' in args else 'disabled'
            unit = n.BRIDGE
            drop = self.directory / (unit + '.d') / '98-amphenol-release-window.conf'
            active = self.s['bridge']
            facts = dict(Id=unit, LoadState='loaded', ActiveState=active, SubState='running' if active == 'active' else 'dead',
                UnitFileState='enabled', MainPID='42' if active == 'active' else '0', ControlPID='0',
                ControlGroup='/fixture-bridge', FragmentPath=str(self.directory / unit),
                DropInPaths=str(drop) if drop.exists() else '', NeedDaemonReload='no')
            return '\n'.join(f'{k}={v}' for k,v in facts.items())
        if op == 'stop': self.s['bridge'] = 'inactive'
        if op == 'start':
            self.s['bridge'] = 'active'
            if self.s.get('fail_bridge_start'):
                self.s['fail_bridge_start'] = False
                raise RuntimeError('fixture post-start failure')
        return ''

    def snapshot(self): return {'wrapper': 'active', 'sync': 'inactive'}
    def close(self, prior):
        Files.ensure_file(self.sentinel, b'')
        self.s['wrapper'] = 'inactive'
    def verify(self, prior): assert self.s['wrapper'] == 'inactive' and self.sentinel.exists()
    def restore(self, prior):
        self.sentinel.unlink(missing_ok=True)
        self.s['wrapper'] = 'active'
    def check_status(self, prior, held=False, restored=False):
        assert self.s['wrapper'] == ('inactive' if held else 'active')
    def check_cgroup(self, group): assert self.s['bridge'] == 'inactive'


def quiet_module(project):
    c = ModuleType('controller')
    c.Systemd, c.present, c.read_object, c.write = FakeSystemd, os.path.lexists, Files.read_object, Files.write
    fake = {
        'controller': c,
        'installer': SimpleNamespace(encode=n.encode),
        'amphenol_operator_one_shot': SimpleNamespace(run_operator_release=lambda **kw: None),
        'amphenol_operator_retained_release': SimpleNamespace(_physical_directory=lambda p: Path(p) if Path(p).is_dir() else None),
        'job_search_helper': ModuleType('job_search_helper'),
        'job_search_helper.cli': SimpleNamespace(PROJECT_ROOT=project, load_environment=lambda p: None,
            state_path=lambda: project / '.state/state.db', job_database_path=lambda: project / '.state/jobs.sqlite3',
            storage_backend=lambda: 'sqlite'),
        'job_search_helper.integration_release': SimpleNamespace(assert_release_settled=lambda p: None),
    }
    with patch.dict(sys.modules, fake):
        return load('window_fixture_quiet', Path(__file__).parent / 'vendor/quiet_window.py')


def initial_exchange(root):
    control = root / 'historical'
    control.mkdir(mode=0o700)
    (control / 'exchange.lock').write_bytes(b'')
    (control / 'exchange.lock').chmod(0o600)
    parent = root / 'routes'
    parent.mkdir()
    pairs = []
    def pin(path, directory=True):
        fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0))
        try: return asdict(X.pin(fd))
        finally: os.close(fd)
    for i in range(3):
        canonical, sentinel = parent / f'copy{i}', parent / f'.exchange-park-{i}'
        canonical.mkdir(); sentinel.mkdir(); sentinel.chmod(0o500)
        (canonical / 'original.txt').write_text(str(i))
        pairs.append(dict(parent=str(parent), canonical=canonical.name, parked=sentinel.name,
                          parent_pin=pin(parent), original_pin=pin(canonical), sentinel_pin=pin(sentinel)))
    policy = dict(schema=X.POLICY_SCHEMA, mode='fixture', generation='1'*32,
        mount_namespace=os.readlink('/proc/self/ns/mnt'), control=str(control), control_pin=pin(control),
        lock_pin=pin(control/'exchange.lock', False), pairs=pairs)
    raw = X.encode(policy)
    (control/'policy.json').write_bytes(raw); (control/'policy.json').chmod(0o600)
    old = X.HostExchange(control/'policy.json', sha256(raw).hexdigest())
    old.prepare(); old.close(); old.restore(b'previous proof', verify_terminal=lambda *_: True)
    return old


class Harness(n.NativeWindow):
    def _approval(self):
        if not self.approved: raise ValueError('no approved candidate')
    def _modules(self): pass
    def _lineage(self, **kwargs): pass
    def _observer(self):
        if not self.observer: raise ValueError('no live observer')
    def _running(self, bridge_allowed):
        if not self.observer: raise ValueError('no live observer')
        if self.fail_readiness: raise RuntimeError('fixture restored readiness failure')
        assert self.system['wrapper'] == 'active'
        assert self.system['bridge'] == ('active' if bridge_allowed else 'inactive')
        return {}
    def _terminal(self, before_only=False):
        if self.nonterminal: raise ValueError('nonterminal application')
        return {'state': 'UNCHANGED_BEFORE', 'release_id': self.release_id, 'manifest_sha256': self.manifest_sha256}
    def ready(self):
        self._approval()
        self._running(bridge_allowed=True)
        if self.journal.exists(): raise ValueError('use recovery')
        return {'state':'READY'}


class NativeComposition(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=X.FIXTURE_BASE)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project / '.state').mkdir()
        (self.project / 'dev/wrapper-coder/repairs').mkdir(parents=True)
        self.deployment = self.project / 'dev/wrapper-coder/repairs/deployment.lock'
        self.deployment.write_bytes(b'')
        self.app_lock = self.project / '.state/scraper.lock'; self.app_lock.write_bytes(b'')
        self.directory = self.root / 'units'; self.directory.mkdir()
        (self.directory/n.BRIDGE).write_text('fixture bridge')
        self.old = initial_exchange(self.root)
        self.history = {p.name:p.read_bytes() for p in self.old.policy_path.parent.iterdir()}
        self.window_root = self.root/'new'; self.window_root.mkdir(mode=0o700)
        self.system = dict(wrapper='active', bridge='active', commands=[])
        FakeSystemd.shared = self.system
        q = quiet_module(self.project)
        self.w = Harness(release_id='REL-'+'a'*24, manifest_sha256='b'*64, manifest={},
            qualification_check=lambda:None, window_root=self.window_root,
            native_modules={'quiet_window':q}, wrapper_scope_sha256='c'*64)
        self.w.c = SimpleNamespace(**{k:getattr(Files,k) for k in ('write','lock','ensure_file','check_file','sync_unlink','ref','gate')}, Systemd=FakeSystemd)
        self.w.x, self.w.historical_exchange = X, self.old
        self.w.units = FakeSystemd(Path('/fixture/systemctl'), self.directory, self.window_root/'operator-hold-active')
        self.w.old = SimpleNamespace(units=self.w.units)
        self.w.bridge = n.BridgeFence(self.w.c,self.w.units,self.window_root)
        self.w.h = SimpleNamespace(verify_listener=lambda *_:True, verify_route_drain=lambda *_:True)
        self.w.policy = SimpleNamespace()
        self.w.approved = self.w.observer = True
        self.w.nonterminal = self.w.fail_readiness = False
        self.w.system = self.system
        self.patches = [patch.object(n,'PROJECT',self.project),
                        patch.object(n,'EXCHANGE_TERMINAL',sha256(b'previous proof').hexdigest())]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()
    def history_preserved(self):
        self.assertEqual(self.history,{p.name:p.read_bytes() for p in self.old.policy_path.parent.iterdir()})
    def test_default_refusals_make_no_effects(self):
        for attr in ('approved','observer'):
            setattr(self.w,attr,False)
            with self.assertRaises(ValueError):
                with self.w.hold(): self.fail('worker entered')
            self.assertEqual(list(self.window_root.iterdir()),[])
            self.assertEqual(self.system['commands'],[])
            setattr(self.w,attr,True)
    def test_real_default_entry_and_fixed_digest_grammar(self):
        real = n.create_window(release_id='REL-'+'a'*24, manifest_sha256='b'*64, manifest={},
            qualification_check=lambda:None, window_root=self.window_root,
            native_modules={}, wrapper_scope_sha256='c'*64)
        with self.assertRaises(ValueError):real.ready()
        self.assertEqual(list(self.window_root.iterdir()),[])
        for name in ('RECEIPT_03','RECEIPT_04','RECEIPT_05','CONTROLLER_RECORD','EXCHANGE_POLICY','EXCHANGE_TERMINAL'):
            self.assertRegex(getattr(n,name),r'^[0-9a-f]{64}$')
        self.assertEqual(n.CONTROLLER_RECORD,'0f2543519bbd7dcf9737533c3e2caebf62e2e8a8cc1574d09287e21055ed1793')
    def test_site_module_origin_requires_pinned_zip_and_members(self):
        bundle=self.root/'capsule';bundle.mkdir()
        archive=bundle/'host-check'
        bodies={name:(name+' fixture').encode() for name in n.MODULE_PINS}
        modules={}
        with ZipFile(archive,'w') as z:
            for name in ('host_checkpoint','site_policy','host_exchange'):
                z.writestr(name+'.py',bodies[name])
                modules[name]=SimpleNamespace(__file__=str(archive/(name+'.py')))
        for name in set(bodies)-set(modules):
            target=bundle/(name+'.py');target.write_bytes(bodies[name])
            modules[name]=SimpleNamespace(__file__=str(target))
        pins={name:sha256(body).hexdigest() for name,body in bodies.items()}
        real=n.create_window(release_id='REL-'+'a'*24,manifest_sha256='b'*64,manifest={},
            qualification_check=lambda:None,window_root=self.window_root,native_modules=modules,
            wrapper_scope_sha256='c'*64)
        with patch.object(n,'BUNDLE',bundle),patch.object(n,'CHECKER_SHA256',sha256(archive.read_bytes()).hexdigest()),patch.object(n,'MODULE_PINS',pins):
            real._modules()
            loose=bundle/'host_checkpoint.py';loose.write_bytes(bodies['host_checkpoint'])
            modules['host_checkpoint'].__file__=str(loose)
            with self.assertRaisesRegex(ValueError,'sealed archive'):real._modules()
            modules['host_checkpoint'].__file__=str(archive/'host_checkpoint.py')
            loose_exchange=bundle/'host_exchange.py';loose_exchange.write_bytes(bodies['host_exchange'])
            modules['host_exchange'].__file__=str(loose_exchange)
            with self.assertRaisesRegex(ValueError,'sealed archive'):real._modules()
            modules['host_exchange'].__file__=str(archive/'host_exchange.py')
            with patch.dict(pins,{'host_checkpoint':'0'*64}):
                with self.assertRaisesRegex(ValueError,'member differs'):real._modules()
            archive.write_bytes(archive.read_bytes()+b'drift')
            with self.assertRaisesRegex(ValueError,'checker differs'):real._modules()
    def test_real_exchange_quiet_window_and_free_worker_lock(self):
        with self.w.hold():
            self.assertEqual(self.system['wrapper'],'inactive')
            self.assertEqual(self.system['bridge'],'inactive')
            with Files.lock(self.app_lock): pass
            with self.assertRaises(BlockingIOError):
                with Files.lock(self.deployment): pass
        self.assertEqual(self.system['wrapper'],'active')
        self.assertEqual(self.system['bridge'],'active')
        self.w.exchange.witness('restored')
        self.history_preserved()
        commands = list(self.system['commands'])
        self.w.restore()
        self.assertEqual([c for c in self.system['commands'][len(commands):] if c[0] in ('stop','start')],[])
    def test_partial_real_swap_recovers_without_worker(self):
        swap = X._exchange
        def interrupted(*args):
            swap(*args)
            raise RuntimeError('fixture crash after first swap before journal')
        with patch.object(X,'_exchange',interrupted), self.assertRaises(RuntimeError):
            with self.w.hold():self.fail('worker entered')
        self.assertEqual(self.system['bridge'],'inactive')
        self.w.restore()
        self.w.exchange.witness('restored')
        self.history_preserved()
    def test_quiet_restore_failure_is_fenced_and_recoverable(self):
        with self.assertRaises(ValueError):
            with self.w.hold(): self.w.fail_readiness=True
        self.assertEqual(self.system['wrapper'],'inactive')
        self.assertEqual(self.system['bridge'],'inactive')
        self.w.fail_readiness=False
        self.w.restore()
        self.assertEqual(self.system['wrapper'],'active')
        self.history_preserved()
    def test_bridge_start_failure_reholds_and_restores_exact_routes(self):
        with self.assertRaises(RuntimeError):
            with self.w.hold(): self.system['fail_bridge_start']=True
        self.assertEqual(self.system['bridge'],'inactive')
        self.w.exchange.witness('restored')
        self.w.restore()
        self.assertEqual(self.system['bridge'],'active')
        self.history_preserved()
    def test_nonterminal_application_blocks_all_restoration(self):
        with self.assertRaises(ValueError):
            with self.w.hold(): self.w.nonterminal=True
        self.assertEqual(self.system['bridge'],'inactive')
        self.w.exchange.witness('closed')
        with self.assertRaises(ValueError):self.w.restore()
        self.w.nonterminal=False
        self.w.restore()
        self.history_preserved()
    def test_recovery_requires_fresh_observer_before_service_actions(self):
        with self.assertRaises(RuntimeError):
            with self.w.hold(): self.system['fail_bridge_start']=True
        commands = list(self.system['commands'])
        self.w.observer=False
        with self.assertRaises(ValueError):self.w.restore()
        self.assertEqual(self.system['commands'], commands)
        self.w.observer=True
        self.w.restore()
        self.history_preserved()


class CompleteHarness(Harness):
    # Keep only external service/observer/lineage boundaries substituted.
    # Exercise the actual default admission, exact app checks and binding.
    ready = n.NativeWindow.ready
    _approval = n.NativeWindow._approval
    _terminal = n.NativeWindow._terminal


class CompleteContinuation(unittest.TestCase):
    setUp = NativeComposition.setUp
    tearDown = NativeComposition.tearDown
    history_preserved = NativeComposition.history_preserved

    def _complete_fixture(self):
        modules = {
            'job_search_helper': ModuleType('job_search_helper'),
            'job_search_helper.cli': SimpleNamespace(scraper_lock_name=lambda: 'scraper.lock', writer_lock=Files.lock),
        }
        patcher = patch.dict(sys.modules, modules)
        patcher.start(); self.addCleanup(patcher.stop)
        load('job_search_helper.repair_retry', Path(__file__).parent/'vendor/repair_retry.py')
        release = load('job_search_helper.integration_release', Path(__file__).parent/'vendor/integration_release.py')
        target = self.project/'src/job_search_helper/acquiretm.py'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'BEFORE = True\n')
        (self.project/'requirements.txt').write_bytes(b'# disposable dependency policy\n')
        before = release.metadata(target)
        before_tree = release.source_tree_digest(self.project)
        target.write_bytes(b'AFTER = True\n')
        manifest = dict(schema=release.MANIFEST_SCHEMA, failed_request_id='operator-fixture',
            company_id='COMP-0490', source_revision='fixture-current-source',
            files={'src/job_search_helper/acquiretm.py': {'before':before,'after':release.metadata(target)}},
            before_source_manifest_sha256=before_tree, source_manifest_sha256=release.source_tree_digest(self.project),
            before_config_sha256=release.config_tree_digest(self.project), config_sha256=release.config_tree_digest(self.project),
            dependency_manifest_sha256=release.dependency_manifest_digest(self.project), validation_receipt_sha256='e'*64)
        manifest['release_id'] = release.manifest_release_id(manifest)
        manifest = release.canonical_manifest(manifest)
        self.w.__class__ = CompleteHarness
        self.w.release_id, self.w.manifest = manifest['release_id'], manifest
        self.w.manifest_sha256 = release.digest(manifest)
        self.w.qualification_check = lambda: {'release_id': self.w.release_id, 'manifest_sha256': self.w.manifest_sha256}
        self.w.resume_complete = True
        journal = dict(schema=release.JOURNAL_SCHEMA, state='COMPLETE', release_id=self.w.release_id,
                       manifest_sha256=self.w.manifest_sha256, release=release.release_binding(manifest))
        path = self.project/'.state/integration-release-journal.json'
        Files.write(path,n.encode(journal))
        bridge = self.directory/n.BRIDGE
        for key, value in [('BRIDGE_UNIT',bridge), ('BRIDGE_SOURCE',bridge),
                           ('BRIDGE_UNIT_SHA',sha256(bridge.read_bytes()).hexdigest()),
                           ('BRIDGE_SOURCE_SHA',sha256(bridge.read_bytes()).hexdigest())]:
            p=patch.object(n,key,value); p.start(); self.patches.append(p)
        return release, path, journal, target

    def test_complete_continuation_real_exchange_and_scoped_restore(self):
        release,path,journal,target = self._complete_fixture()
        originals = {path:path.read_bytes(),target:target.read_bytes()}
        self.assertEqual(self.w.ready()['state'],'QUALIFIED_NATIVE_WINDOW_READY')
        self.assertEqual(list(self.window_root.iterdir()),[])
        yielded = []
        with self.assertRaises(ValueError):
            with self.w.hold():
                yielded.append('existing application resume only')
                with Files.lock(self.app_lock): pass
                self.w.fail_readiness = True
        self.assertEqual(self.system['wrapper'],'inactive')
        self.assertEqual(self.system['bridge'],'inactive')
        self.assertEqual(json.loads(self.w.journal.read_bytes())['binding']['continuation'],
                         'same-qualified-complete-release-v1')
        # Recovery cannot reinterpret this continuation as an initial install.
        self.w.resume_complete=False
        commands=list(self.system['commands'])
        with self.assertRaisesRegex(ValueError,'Unknown native recovery'):self.w.restore()
        self.assertEqual(commands,self.system['commands'])
        self.w.resume_complete=True; self.w.fail_readiness=False
        path.unlink()
        commands=list(self.system['commands'])
        with self.assertRaises((ValueError,RuntimeError)):self.w.restore()
        self.assertEqual(commands,self.system['commands'])
        Files.write(path,originals[path])
        self.w.restore(); self.w.restore()
        self.assertEqual(yielded,['existing application resume only'])
        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
        self.w.exchange.witness('restored'); self.history_preserved()
        with self.assertRaisesRegex(ValueError,'Existing window'):
            with self.w.hold(): self.fail('spent window reused')

    def test_complete_continuation_refuses_missing_wrong_or_changed_active_release(self):
        release,path,journal,target = self._complete_fixture()
        original=path.read_bytes()
        variants=[None, {**journal,'state':'ROLLED_BACK'}, {**journal,'release_id':'REL-'+'f'*24},
                  {**journal,'manifest_sha256':'f'*64}, {**journal,'release':{}},
                  {**journal,'release':{**journal['release'],'source_manifest_sha256':'f'*64}}]
        for value in variants:
            if value is None:path.unlink()
            else:Files.write(path,n.encode(value),replace=path.exists())
            with self.assertRaises((ValueError,RuntimeError)):
                with self.w.hold():self.fail('invalid activation entered worker')
            self.assertEqual(list(self.window_root.iterdir()),[])
            self.assertEqual(self.system['commands'],[])
        Files.write(path,original,replace=True)
        target.write_bytes(b'DRIFT = True\n')
        with self.assertRaisesRegex(ValueError,'Settled source'):
            with self.w.hold():self.fail('changed source entered worker')
        self.assertEqual(list(self.window_root.iterdir()),[])

    def test_default_admission_still_requires_before_and_same_qualified_approval(self):
        release,path,journal,target = self._complete_fixture()
        self.w.resume_complete=False
        with self.assertRaisesRegex(ValueError,'Different active release'):self.w.ready()
        path.unlink();target.write_bytes(b'BEFORE = True\n')
        self.assertEqual(self.w.ready()['state'],'QUALIFIED_NATIVE_WINDOW_READY')
        self.w.resume_complete=True
        self.w.qualification_check=lambda:None
        commands=list(self.system['commands'])
        with self.assertRaisesRegex(ValueError,'independent live qualification'):self.w.ready()
        self.assertEqual(commands,self.system['commands'])
        self.assertEqual(list(self.window_root.iterdir()),[])


if __name__=='__main__':
    unittest.main(verbosity=2)

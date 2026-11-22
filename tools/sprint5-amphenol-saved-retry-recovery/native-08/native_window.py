"""Private, default-off -08 verified-note maintenance composition; no import effects.

The release entry owns its qualification owner and measured module loader.
This module never installs source, opens application databases or runs a worker.
"""

from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import time
from uuid import uuid4
from zipfile import ZipFile

PROJECT = Path('/home/chris/job-search-helper_old')
BUNDLE = Path('/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03')
CURRENT = BUNDLE.with_name('s5-amphenol-two-tool-20261121-05')
MAINTENANCE_ID = 's5-amphenol-verified-notes-20261122-08'
OBSERVER = Path('/run/jsh-s5-amphenol-verified-notes-08/observer.sock')
BRIDGE = 'jetson-assistant-bridge.service'
WRAPPER = 'wrapper-development-host.service'
SYNC = 'job-search-sync.service'
TIMER = 'job-search-sync-expiry.timer'
BRIDGE_UNIT = Path('/home/chris/.config/systemd/user') / BRIDGE
BRIDGE_UNIT_SHA = '14bb10660f819d255155f5fdb70c85d2215c7673963ef6678f27ee263db3dfdc'
BRIDGE_SOURCE = Path('/home/chris/AI/assistant-tools-bridge/bridge.py')
BRIDGE_SOURCE_SHA = 'fa6b6b5655797c36ead623f3dae01285a251b9fe266d696a00d44114ed1099d9'
RECEIPT_05 = '60b29ffc98f4ef35399f9c9fdefe949f42f34b928a35b51e766dc0ba41d480cf'
RECEIPT_04 = 'e07eab1cf86378f6b6fe0055763a83bb212b52626774fb6d0fe0366f311b7dc3'
RECEIPT_03 = 'eecbb742a212acdfb30a7be7687daf90dd8cb348a4076b7041680ad2d1243058'
CONTROLLER_RECORD = '0f2543519bbd7dcf9737533c3e2caebf62e2e8a8cc1574d09287e21055ed1793'
EXCHANGE_POLICY = 'e35dac07cceb74964349c0daf14524e2555e213bb27ae740edc24e320765cd7b'
EXCHANGE_TERMINAL = 'c092dfc357a96f13c4b8c02740e89caa6430228239630edb80a1acadf82dcb25'
CHECKER_SHA256 = 'c0bec31ab59dbdc1064e2ee7003b9aa68e115d5902c34e43ebbe75058bf2a53e'
HOST = 'dev/wrapper-coder/tools/host_server.py'
STORE = 'dev/wrapper-coder/tools/coordinator_store.py'
CURRENT_TOOLS = {
    HOST: 'a1cafe60d2025116bcaa43dd8dd1b4099a9c2845c35353f3f25dec98a8df5567',
    STORE: '16c442d8019d5173f188348890fd89fe224d2c4315fde67528ed26e25478134d',
}
PREDECESSOR_06 = BUNDLE.with_name('s5-amphenol-qualified-release-20261121-06')
PREDECESSOR_06_NATIVE = 'a6df3c1d196187183d1185a718c2a643c4124d4af9f878157c553c4927d235c1'
PREDECESSOR_06_QUIET = 'f7cf92c27f1cc72cecdf5d13b10b9a3afab5b89fed59aafceafd2471e6f4c437'
PREDECESSOR_06_EXCHANGE = 'ae77b6e09c7d2958e059d9fa8c8315125012a6193d6662111e5a3785cb8deabe'
PREDECESSOR_06_BINDING = {
    'schema': 'amphenol-native-window-v1',
    'maintenance_id': 's5-amphenol-qualified-release-20261121-06',
    'release_id': 'REL-f509ed362bf8781ea8840adc',
    'manifest_sha256': '0b3cdefdc414cd70716cb66d8f375389d91f3f1092489c3432202fec95f4eda0',
    'predecessor_receipt_sha256': RECEIPT_05,
    'observer': '/run/jsh-s5-amphenol-release-06/observer.sock',
    'wrapper_scope_sha256': '43a043c7e33e34c2c25730fa5344bf8441c5c9a4e5323341f821ab506bb6c0f1',
}
PREDECESSOR_06_EXCHANGE_TERMINAL = '894cd4410ee656f945c24791b166e6eb893d23723af21cb9aa6471419aecaa30'
PREDECESSOR_07 = BUNDLE.with_name('s5-amphenol-saved-retry-20261121-07')
PREDECESSOR_07_NATIVE = '7c53942353570ea097213c847f20c69c6cb9044c78ad7483367d999e5e37b0e0'
PREDECESSOR_07_QUIET = '1a94d33737b8721391d637600b19e4a4e6fc389ab2497c04781d8a8093ea9060'
PREDECESSOR_07_EXCHANGE = '108d65679bfd4ec72af85c1ddd4fb54f45eb7a04146222460569112e0ae381a5'
PREDECESSOR_07_TERMINAL = '58a75e3a3eb2be3198eba6e9917bd5c5bf8785ccd2abe9e048a7aae74c4f0e4a'
MODULE_PINS = {
    'controller': 'f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8',
    'host_exchange': '8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f',
    'host_checkpoint': 'fe5ac8bed3ab1e88ff645859ba6f156229694643d3b3549415748c8952016e43',
    'site_policy': '1c190dcf0b15017af8ab8d2b351726361750506bc07ceac97c5eb1926e7681cd',
    'two_tool_route_drain': 'aac2a747a6389f3e98e7e38dad9ce562e9f80c6ed1a039d0d2b5e6ac3d539b25',
    'quiet_window': '8b124170b12897dcc37a82d6a5af5ed38538fee22d9194ddf4146c2565a2fdc4',
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def physical(path, *, directory=False):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'Physical absolute path required')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 'Wrong path kind')
    return path


def read_private(path, expected=None):
    path = physical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(before.st_nlink == 1 and before.st_uid == os.geteuid()
                and stat.S_IMODE(before.st_mode) == 0o600, 'Private single-link record required')
        raw = stream.read(512 * 1024 + 1)
        after = path.lstat()
        require(os.path.samestat(before, after) and before.st_ctime_ns == after.st_ctime_ns
                and len(raw) <= 512 * 1024, 'Private record changed')
    require(expected is None or sha256(raw).hexdigest() == expected, 'Approved record differs')
    return raw


def reenroll_exchange(exchange_module, historical_exchange, control):
    """Fresh control/journal; reuses only the validated restored endpoint pins."""
    witness = historical_exchange.witness('restored')
    old_policy = exchange_module.load_policy(historical_exchange.policy_path,
                                              historical_exchange.approved_sha256)
    require(witness.terminal_proof_sha256 == EXCHANGE_TERMINAL, 'Historical restoration differs')
    control = Path(control)
    require(not os.path.lexists(control) and physical(control.parent, directory=True), 'Fresh exchange required')
    control.mkdir(mode=0o700)
    with open(control / 'exchange.lock', 'xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.flush()
        os.fsync(stream.fileno())
    with exchange_module._directory(control) as directory:
        lock = os.open('exchange.lock', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            control_pin = asdict(exchange_module.pin(directory))
            lock_pin = asdict(exchange_module.pin(lock))
        finally:
            os.close(lock)
    raw = json.loads(read_private(historical_exchange.policy_path, old_policy.sha256))
    raw.update(control=str(control), generation=uuid4().hex,
               control_pin=control_pin, lock_pin=lock_pin)
    encoded = encode(raw)
    with open(control / 'policy.json', 'xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    fresh = exchange_module.HostExchange(control / 'policy.json', sha256(encoded).hexdigest(),
                                          enable_host_writes=True)
    intent = fresh.prepare()
    return fresh, {'policy_sha256': sha256(encoded).hexdigest(), 'intent_sha256': intent,
                   'generation': raw['generation']}


class BridgeFence:
    """The existing Systemd condition pattern, limited to the assistant bridge."""
    def __init__(self, controller, units, directory):
        self.controller, self.units = controller, units
        self.sentinel = directory / 'bridge-hold-active'
        self.path = units.directory / (BRIDGE + '.d') / '98-amphenol-release-window.conf'
        self.data = f'[Unit]\nConditionPathExists=!{self.sentinel}\n'.encode()

    def status(self):
        raw = self.units.command('show', '--all',
            *(f'--property={key}' for key in self.units.PROPERTIES), BRIDGE)
        result = dict(line.split('=', 1) for line in raw.strip().splitlines())
        require(set(result) == set(self.units.PROPERTIES) and result['Id'] == BRIDGE
                and result['LoadState'] == 'loaded' and result['NeedDaemonReload'] == 'no',
                'Bridge status is incomplete')
        return result

    def files(self, status):
        return {name: self.controller.ref(Path(name)) for name in
                [status['FragmentPath'], *status['DropInPaths'].split()] if name != str(self.path)}

    def snapshot(self):
        status = self.status()
        require(status['ActiveState'] == 'active' and status['UnitFileState'] == 'enabled'
                and int(status['MainPID']) > 0 and status['ControlGroup']
                and not os.path.lexists(self.path) and not os.path.lexists(self.sentinel),
                'Bridge must begin active/enabled without another fence')
        return {'active': status['ActiveState'], 'enabled': status['UnitFileState'],
                'cgroup': status['ControlGroup'], 'files': self.files(status),
                'had_dropin_directory': self.path.parent.exists()}

    def verify(self, prior, *, held):
        current = self.status()
        require(self.files(current) == prior['files'] and current['UnitFileState'] == prior['enabled']
                and (str(self.path) in current['DropInPaths'].split()) == held
                and current['ActiveState'] == ('inactive' if held else prior['active']),
                'Bridge configuration or activity changed')
        if held:
            self.controller.check_file(self.path, self.data, 0o644)
            self.controller.check_file(self.sentinel, b'', 0o600)
            require(current['DropInPaths'].split()[-1] == str(self.path)
                    and current['MainPID'] == current['ControlPID'] == '0', 'Bridge fence is not effective')
            for group in {prior['cgroup'], current['ControlGroup']} - {''}:
                self.units.check_cgroup(group)
        return True

    def close(self, prior):
        self.controller.ensure_file(self.sentinel, b'')
        self.path.parent.mkdir(exist_ok=True, mode=0o755)
        physical(self.path.parent, directory=True)
        self.controller.gate.syncdir(self.path.parent.parent)
        self.controller.ensure_file(self.path, self.data, 0o644)
        self.units.command('daemon-reload', timeout=30)
        self.units.command('stop', BRIDGE, timeout=65)
        self.verify(prior, held=True)

    def restore(self, prior):
        try:
            if os.path.lexists(self.path):
                self.controller.check_file(self.path, self.data, 0o644)
                self.controller.sync_unlink(self.path)
            if not prior['had_dropin_directory'] and self.path.parent.exists():
                self.path.parent.rmdir()
                self.controller.gate.syncdir(self.path.parent.parent)
            self.units.command('daemon-reload', timeout=30)
            if os.path.lexists(self.sentinel):
                self.controller.check_file(self.sentinel, b'', 0o600)
                self.controller.sync_unlink(self.sentinel)
            if self.status()['ActiveState'] != prior['active']:
                self.units.command('start', BRIDGE, timeout=45)
            self.verify(prior, held=False)
        except BaseException:
            self.close(prior)
            raise


class NativeWindow:
    def __init__(self, *, release_id, manifest_sha256, manifest, qualification_check,
                 window_root, native_modules, wrapper_scope_sha256, resume_complete=True):
        require(resume_complete is True, 'Saved-retry window requires exact COMPLETE continuation')
        self.resume_complete = resume_complete
        self.release_id, self.manifest_sha256, self.manifest = release_id, manifest_sha256, manifest
        self.qualification_check, self.root = qualification_check, Path(window_root)
        self.modules, self.wrapper_scope_sha256 = native_modules, wrapper_scope_sha256
        self.journal = self.root / 'native-window.json'
        self._held = False

    def _modules(self):
        require(set(self.modules) == set(MODULE_PINS), 'Exact native modules required')
        for name, digest in MODULE_PINS.items():
            origin = Path(self.modules[name].__file__)
            if name in {'host_checkpoint', 'site_policy', 'host_exchange'}:
                archive = BUNDLE / 'host-check'
                require(origin == archive / (name + '.py'), 'Site modules must come from the exact sealed archive')
                raw = physical(archive).read_bytes()
                require(sha256(raw).hexdigest() == CHECKER_SHA256, 'Sealed host checker differs')
                with ZipFile(BytesIO(raw)) as package:
                    require(sha256(package.read(name + '.py')).hexdigest() == digest,
                            'Sealed site member differs')
            else:
                path = physical(origin)
                require(sha256(path.read_bytes()).hexdigest() == digest, 'Native module pin differs')
        self.c = self.modules['controller']
        self.x = self.modules['host_exchange']
        self.h = self.modules['host_checkpoint']
        self.r = self.modules['two_tool_route_drain']

    def _approval(self):
        require(callable(self.qualification_check) and self.qualification_check() == {
            'release_id': self.release_id, 'manifest_sha256': self.manifest_sha256},
            'Exact independent live qualification required before maintenance')
        from job_search_helper.integration_release import canonical_manifest, digest
        exact = canonical_manifest(self.manifest)
        require(exact == self.manifest and exact['release_id'] == self.release_id
                and digest(exact) == self.manifest_sha256 and exact['company_id'] == 'COMP-0490'
                and set(exact['files']) == {'src/job_search_helper/acquiretm.py'}, 'Wrong qualified app proposal')

    def _lineage(self, *, check_restored=True):
        current = json.loads(read_private(CURRENT / 'two-tool-forward-receipt.json', RECEIPT_05))
        forward = BUNDLE.with_name('s5-amphenol-host-source-20261121-04') / 'host-forward-receipt.json'
        read_private(forward, RECEIPT_04)
        require(current['status'] == 'TWO_TOOL_FORWARD_INSTALLED'
                and current['predecessor'] == {'receipt_sha256': RECEIPT_04, 'terminal_source': 'INSTALLED'}
                and current['historical_predecessor_receipt_sha256'] == RECEIPT_03
                and set(current['paths']) == set(CURRENT_TOOLS), 'Current -05 lineage differs')
        self._require_predecessor_06_restored()
        self._require_predecessor_07_restored()
        self.old = self.c.Controller(BUNDLE)
        raw = read_private(self.old.journal, CONTROLLER_RECORD)
        record = self.old.load(canonical=True)
        require(self.c.installer.encode(record) == raw and record['phase'] == 'RELEASED'
                and record['target'] == 'INSTALLED'
                and sha256(self.c.installer.encode(record['receipt'])).hexdigest() == RECEIPT_03,
                'Historical terminal differs')
        transaction = read_private(self.old.state / self.c.installer.JOURNAL)
        require(transaction == self.c.installer.encode({**record['receipt'], 'owners': self.old.manifest.owners}),
                'Historical installer transaction differs')
        package, parked = self.old.package(record)
        require(not parked and package == self.old.canonical, 'Canonical source is parked')
        with self.old.package_directory(record, package) as directory:
            self.old.check_extension(record, directory, guarded=False)
        expected = dict(self.old.manifest.after)
        expected[HOST] = (expected[HOST][0], CURRENT_TOOLS[HOST])
        require(self.c.scope(PROJECT, False, self.old.manifest.paths, self.old.manifest.owners) == expected,
                'Historical scoped source differs')
        for relative, digest in CURRENT_TOOLS.items():
            info = current['paths'][relative]
            actual = self.c.ref(PROJECT / relative)
            require(info['after_sha256'] == digest and actual[-1] == digest
                    and actual[2] == int(info['mode'], 8) and actual[3] == os.geteuid(),
                    'Current tool bytes differ')
        require(re.fullmatch('[a-f0-9]{64}', self.wrapper_scope_sha256 or '')
                and self.c.unscoped(self.old.wrapper_tools, set()) == self.wrapper_scope_sha256,
                'Fresh independently measured wrapper directory differs')
        with self.c.installer.source_tree(PROJECT, False) as tree:
            directories = self.c.installer.source_directories(tree)
            with self.c.installer.directory(self.c.gate.PARKED, tree['src']) as guard:
                directories.update(self.c.installer.source_directories({'guard': guard}))
        require(directories == record['receipt']['source_directories']
                and directories['guard']['identity'] == record['guard'], 'Physical source guard differs')
        self.historical_exchange = self.x.HostExchange(BUNDLE / 'exchange-private/policy.json', EXCHANGE_POLICY)
        if check_restored:
            witness = self.historical_exchange.witness('restored')
            require(witness.terminal_proof_sha256 == EXCHANGE_TERMINAL and len(witness.pairs) == 3,
                    'Historical routes are not restored')
        else:
            # Fresh closure legitimately exchanges these same physical pairs.
            # The immutable original receipt remains pinned; its old placement
            # assertion must not be replayed while the fresh owner holds them.
            original = json.loads(read_private(BUNDLE / 'exchange-private/exchange.json'))
            require(original['phase'] == 'restored'
                    and original['terminal_proof_sha256'] == EXCHANGE_TERMINAL
                    and original['intent']['policy_sha256'] == EXCHANGE_POLICY,
                    'Historical exchange receipt changed during fresh hold')
        policy, *_ = self.modules['site_policy'].load_policy(str(BUNDLE / 'host-check'))
        self.policy = replace(policy, maintenance_id=MAINTENANCE_ID, ancillary_process_evidence=OBSERVER,
                              before_host=replace(policy.before_host, digest=CURRENT_TOOLS[HOST]),
                              after_host=replace(policy.after_host, digest=CURRENT_TOOLS[HOST]))

    @staticmethod
    def _require_predecessor_06_restored():
        """Require exact -06 native, quiet, and exchange restoration before -07."""
        native = json.loads(read_private(PREDECESSOR_06 / 'native-window.json', PREDECESSOR_06_NATIVE))
        quiet = json.loads(read_private(PREDECESSOR_06 / 'operator-quiet-window.json', PREDECESSOR_06_QUIET))
        exchange = json.loads(read_private(PREDECESSOR_06 / 'exchange-private/exchange.json', PREDECESSOR_06_EXCHANGE))
        require(native.get('phase') == 'RESTORED' and native.get('binding') == PREDECESSOR_06_BINDING
                and isinstance(native.get('restoration_sha256'), str)
                and re.fullmatch('[a-f0-9]{64}', native['restoration_sha256']) is not None,
                'Prior -06 native continuation is not restored')
        require(quiet.get('phase') == 'RESTORED', 'Prior -06 quiet window is not restored')
        require(exchange.get('phase') == 'restored'
                and exchange.get('terminal_proof_sha256') == PREDECESSOR_06_EXCHANGE_TERMINAL
                and isinstance(exchange.get('intent_sha256'), str)
                and re.fullmatch('[a-f0-9]{64}', exchange['intent_sha256']) is not None,
                'Prior -06 exchange is not restored')

    @staticmethod
    def _require_predecessor_07_restored():
        native = json.loads(read_private(PREDECESSOR_07 / 'native-window.json', PREDECESSOR_07_NATIVE))
        quiet = json.loads(read_private(PREDECESSOR_07 / 'operator-quiet-window.json', PREDECESSOR_07_QUIET))
        exchange = json.loads(read_private(PREDECESSOR_07 / 'exchange-private/exchange.json', PREDECESSOR_07_EXCHANGE))
        require(native['phase'] == quiet['phase'] == 'RESTORED' and exchange['phase'] == 'restored'
                and native['binding']['continuation'] == 'same-qualified-complete-release-v1'
                and native['binding']['release_id'] == PREDECESSOR_06_BINDING['release_id']
                and native['binding']['manifest_sha256'] == PREDECESSOR_06_BINDING['manifest_sha256']
                and native['restoration_sha256'] == exchange['terminal_proof_sha256'] == PREDECESSOR_07_TERMINAL,
                'Prior -07 same-release window is not restored')

    def _running(self, *, bridge_allowed):
        status = self.h.unit_status(self.policy.systemctl, WRAPPER)
        require(status['ActiveState'] == 'active' and status['UnitFileState'] == 'enabled', 'Wrapper is not ready')
        pid = int(status['MainPID'])
        self.h.verify_wrapper_process(self.policy, pid, Path('/proc'))
        listening = self.h.verify_listener(self.policy, pid, Path('/proc'))
        for helper in (1249, 4467):
            require(self.h.verify_ancillary_process(OBSERVER, Path('/proc') / str(helper),
                    self.policy.launch_uid, MAINTENANCE_ID, self.h.checkout_routes(self.policy),
                    listener=(self.policy.wrapper_port, listening)) is True,
                    'Fresh -08 administrator observation is required')
        if bridge_allowed:
            bridge = self.h.unit_status(self.policy.systemctl, BRIDGE)
            bridge_pid = int(bridge['MainPID'])
            require(bridge['ActiveState'] == 'active' and bridge['UnitFileState'] == 'enabled', 'Bridge is not ready')
            self.r.verify_two_tool_route_drain(self.policy, pid, Path('/proc'),
                (bridge_pid, self.h.process_start(Path('/proc') / str(bridge_pid))))
        else:
            self.h.verify_route_drain(self.policy, pid, Path('/proc'))
        return status

    def _observer(self):
        """Authenticate the same fresh observation before recovery can mutate."""
        status = self.h.unit_status(self.policy.systemctl, WRAPPER)
        require(status['ActiveState'] in {'active', 'inactive'}, 'Unsettled wrapper during recovery')
        pid = int(status['MainPID']) if status['ActiveState'] == 'active' else 0
        if pid:
            self.h.verify_wrapper_process(self.policy, pid, Path('/proc'))
        else:
            require(status['MainPID'] == status['ControlPID'] == '0', 'Wrapper process survived hold')
        listening = self.h.verify_listener(self.policy, pid, Path('/proc'))
        for helper in (1249, 4467):
            require(self.h.verify_ancillary_process(OBSERVER, Path('/proc') / str(helper),
                self.policy.launch_uid, MAINTENANCE_ID, self.h.checkout_routes(self.policy),
                listener=(self.policy.wrapper_port, listening) if pid else None) is True,
                'Fresh -08 administrator observation is required before restoration')

    def _running_ready(self, *, bridge_allowed):
        # Existing service startup readiness pattern: observe again, never
        # issue a second restart in response to an early listener observation.
        deadline = time.monotonic() + 12
        while True:
            try:
                return self._running(bridge_allowed=bridge_allowed)
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.3)

    def ready(self):
        """Inspect only. In particular this creates no lock, journal or policy."""
        require(self.resume_complete is True, 'Saved-retry window requires exact COMPLETE continuation')
        self._approval()
        self._modules()
        physical(self.root, directory=True)
        require(stat.S_IMODE(self.root.stat().st_mode) == 0o700 and self.root.stat().st_uid == os.geteuid()
                and self.root != PROJECT and PROJECT not in self.root.parents
                and self.root not in PROJECT.parents, 'Independent private window directory required')
        require(not os.path.lexists(self.journal), 'Existing window requires explicit recovery')
        self._lineage()
        self._terminal(before_only=not self.resume_complete)
        self._running(bridge_allowed=True)  # current observer is required by real process checks
        for path, digest in ((BRIDGE_UNIT, BRIDGE_UNIT_SHA), (BRIDGE_SOURCE, BRIDGE_SOURCE_SHA)):
            require(sha256(physical(path).read_bytes()).hexdigest() == digest, 'Approved bridge source differs')
        self.units = self.c.Systemd(self.old.units.exe, self.old.units.directory, self.root / 'operator-hold-active')
        self.bridge = BridgeFence(self.c, self.units, self.root)
        self.units.snapshot()
        self.bridge.snapshot()
        require(self.units.command('show', TIMER, '-p', 'ActiveState', '--value').strip() == 'inactive'
                and self.units.command('show', TIMER, '-p', 'UnitFileState', '--value').strip() == 'disabled',
                'Scheduled sync timer must remain off')
        return {'state': 'QUALIFIED_NATIVE_WINDOW_READY', 'release_id': self.release_id,
                'manifest_sha256': self.manifest_sha256, 'maintenance_id': MAINTENANCE_ID,
                'observer': str(OBSERVER)}

    def _terminal(self, before_only=False):
        from job_search_helper.integration_release import (assert_release_settled, source_tree_digest,
            config_tree_digest, dependency_manifest_digest)
        journal = assert_release_settled(PROJECT / '.state')
        if self.resume_complete:
            from job_search_helper.integration_release import assert_active_release_binding, release_binding
            active = assert_active_release_binding(PROJECT / '.state', release_binding(self.manifest))
            require(active == journal and not before_only, 'Continuation requires the exact active COMPLETE release')
        after = journal is not None and journal.get('state') == 'COMPLETE'
        if after:
            require(not before_only and journal.get('release_id') == self.release_id
                    and journal.get('manifest_sha256') == self.manifest_sha256, 'Different active release')
        else:
            require(journal is None or (journal.get('state') == 'ROLLED_BACK'
                    and journal.get('release_id') == self.release_id
                    and journal.get('manifest_sha256') == self.manifest_sha256), 'Unexpected prior release')
        require(source_tree_digest(PROJECT) == self.manifest[
                    'source_manifest_sha256' if after else 'before_source_manifest_sha256']
                and config_tree_digest(PROJECT) == self.manifest['config_sha256' if after else 'before_config_sha256']
                and dependency_manifest_digest(PROJECT) == self.manifest['dependency_manifest_sha256'],
                'Settled source/config/dependencies differ')
        return {'state': 'QUALIFIED_RELEASE_SETTLED' if after else 'UNCHANGED_BEFORE',
                'release_id': self.release_id, 'manifest_sha256': self.manifest_sha256}

    def _binding(self):
        binding = {'schema': 'amphenol-native-window-v1', 'maintenance_id': MAINTENANCE_ID,
                'release_id': self.release_id, 'manifest_sha256': self.manifest_sha256,
                'predecessor_receipt_sha256': RECEIPT_05, 'observer': str(OBSERVER),
                'wrapper_scope_sha256': self.wrapper_scope_sha256}
        if self.resume_complete:
            binding['continuation'] = 'same-qualified-complete-release-v1'
        return binding

    def _save(self, record, phase):
        if os.path.lexists(self.journal):
            previous = json.loads(read_private(self.journal))
            require(previous['binding'] == self._binding(), 'Foreign native journal')
        self.c.write(self.journal, encode({**record, 'phase': phase}), replace=os.path.lexists(self.journal))

    @contextmanager
    def _admitted(self):
        require(self._held, 'Deployment exclusion is not held')
        yield

    def _quiet(self):
        def excluded():
            self.bridge.verify(self.record['bridge_prior'], held=True)
            self.exchange.witness('closed')
            self.h.verify_listener(self.policy, 0, Path('/proc'))
            self.h.verify_route_drain(self.policy, 0, Path('/proc'))
            if self.resume_complete:
                # Recheck after writer exclusion, before yielding to the existing retry owner.
                self._terminal()
            return True

        def restored(prior):
            self.bridge.verify(self.record['bridge_prior'], held=True)
            self.exchange.witness('closed')
            self._terminal()
            self._running_ready(bridge_allowed=False)
            return True

        return self.modules['quiet_window'].OperatorQuietWindow(self.units,
            self.root / 'operator-quiet-window.json', self.release_id, PROJECT / '.state',
            admission=self._admitted, verify_exclusion=excluded, verify_restored=restored)

    def _restore_routes_and_bridge(self):
        terminal = self._terminal()
        evidence = encode({'binding': self._binding(), 'terminal': terminal,
                           'exchange': self.record['exchange']})
        self._save(self.record, 'ROUTES_RESTORING')
        self.exchange.restore(evidence, verify_terminal=lambda closed, raw:
            raw == evidence and closed.intent_sha256 == self.record['exchange']['intent_sha256']
            and self._terminal() == terminal)
        self._save(self.record, 'BRIDGE_RESTORING')
        self.bridge.restore(self.record['bridge_prior'])
        self._running_ready(bridge_allowed=True)
        self._save({**self.record, 'terminal': terminal, 'restoration_sha256': sha256(evidence).hexdigest()}, 'RESTORED')

    @contextmanager
    def hold(self):
        """Only deployment.lock persists across the worker, never app locks."""
        self.ready()
        lock = physical(PROJECT / 'dev/wrapper-coder/repairs/deployment.lock')
        with self.c.lock(lock):
            self.ready()
            self._held = True
            try:
                self.exchange, exchange_binding = reenroll_exchange(self.x, self.historical_exchange,
                                                                     self.root / 'exchange-private')
                self.record = {'binding': self._binding(), 'bridge_prior': self.bridge.snapshot(),
                               'exchange': exchange_binding}
                self._save(self.record, 'BRIDGE_CLOSING')
                self.bridge.close(self.record['bridge_prior'])
                self._save(self.record, 'ROUTES_CLOSING')
                self.exchange.close()
                self._save(self.record, 'HELD')
                try:
                    with self._quiet().hold():
                        yield
                finally:
                    # The quiet-window journal must prove its own service restore.
                    saved = json.loads(read_private(self.root / 'operator-quiet-window.json'))
                    require(saved['phase'] == 'RESTORED', 'Wrapper window remains held; explicit recovery required')
                    self._restore_routes_and_bridge()
            finally:
                self._held = False

    def restore(self):
        """Continue only this exact window's restoration; never rerun its worker."""
        require(self.resume_complete is True, 'Saved-retry window requires exact COMPLETE continuation')
        self._approval()
        self._modules()
        physical(self.root, directory=True)
        require(stat.S_IMODE(self.root.stat().st_mode) == 0o700, 'Private window directory required')
        lock = physical(PROJECT / 'dev/wrapper-coder/repairs/deployment.lock')
        with self.c.lock(lock):
            self._held = True
            try:
                self._lineage(check_restored=False)
                self._observer()
                if self.resume_complete:
                    self._terminal()
                self.record = json.loads(read_private(self.journal))
                require(self.record['binding'] == self._binding()
                        and self.record['phase'] in {'BRIDGE_CLOSING', 'ROUTES_CLOSING', 'HELD',
                            'ROUTES_RESTORING', 'BRIDGE_RESTORING', 'RESTORED'}, 'Unknown native recovery state')
                self.units = self.c.Systemd(self.old.units.exe, self.old.units.directory,
                                             self.root / 'operator-hold-active')
                self.bridge = BridgeFence(self.c, self.units, self.root)
                self.exchange = self.x.HostExchange(self.root / 'exchange-private/policy.json',
                    self.record['exchange']['policy_sha256'], enable_host_writes=True)
                exchange_record = json.loads(read_private(self.root / 'exchange-private/exchange.json'))
                require(exchange_record['intent_sha256'] == self.record['exchange']['intent_sha256'],
                        'Fresh exchange recovery identity changed')
                if self.record['phase'] == 'RESTORED':
                    self.exchange.witness('restored')
                    self.bridge.verify(self.record['bridge_prior'], held=False)
                    require(self._terminal() == self.record['terminal'], 'Terminal release changed')
                    self._running(bridge_allowed=True)
                    return {'state': 'NATIVE_WINDOW_RESTORED', 'release_id': self.release_id}
                # No automatic replay of the release or provider. A partial
                # outer close is completed only to get the existing exchange's
                # exact supported restoration proof, then immediately restored.
                self.bridge.close(self.record['bridge_prior'])
                if exchange_record['phase'] in {'closing', 'closed', self.x.CLOSED_ACKNOWLEDGED}:
                    self.exchange.close()
                    quiet_path = self.root / 'operator-quiet-window.json'
                    if os.path.lexists(quiet_path):
                        self._quiet().restore()
                    else:
                        self._terminal()
                        self._running(bridge_allowed=False)
                else:
                    require(exchange_record['phase'] in {'restoring', 'restored'}, 'Unknown exchange phase')
                    quiet_record = json.loads(read_private(self.root / 'operator-quiet-window.json'))
                    require(quiet_record['phase'] == 'RESTORED', 'Wrapper restoration not proven')
                    self.units.check_status(quiet_record['prior'], held=False, restored=True)
                    self._terminal()
                    self._running(bridge_allowed=False)
                self._restore_routes_and_bridge()
                return {'state': 'NATIVE_WINDOW_RESTORED', 'release_id': self.release_id}
            finally:
                self._held = False


def create_window(**kwargs):
    return NativeWindow(**kwargs)

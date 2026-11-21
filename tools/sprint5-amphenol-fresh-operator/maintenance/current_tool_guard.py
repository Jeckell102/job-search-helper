"""Admit the two-tool Amphenol update from the verified -04 source."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
import os
import stat


FORWARD_RECEIPT_SHA256 = 'e07eab1cf86378f6b6fe0055763a83bb212b52626774fb6d0fe0366f311b7dc3'
HOST_RELATIVE = 'dev/wrapper-coder/tools/host_server.py'


class CurrentToolGuard:
    def __init__(self, controller, controller_module, forward_receipt, verify_host_exclusion):
        self.controller = controller
        self.controller_module = controller_module
        self.forward_receipt = forward_receipt
        self.verify_host_exclusion = verify_host_exclusion

    @contextmanager
    def terminal(self):
        old = self.controller
        existing = self.controller_module
        with ExitStack() as stack:
            for path in (old.controller_gate, *old.locks, old.install_gate):
                stack.enter_context(existing.lock(path))
            if {str(path): existing.inode(path) for path in old.locks} != old.binding['locks']:
                raise ValueError('Established application lock identity changed.')

            path = existing.physical(self.forward_receipt)
            raw, attrs = existing.read(path)
            if (sha256(raw).hexdigest() != FORWARD_RECEIPT_SHA256
                    or not stat.S_ISREG(attrs.st_mode) or stat.S_IMODE(attrs.st_mode) != 0o600
                    or attrs.st_uid != os.geteuid() or attrs.st_nlink != 1):
                raise ValueError('Verified -04 successor receipt changed.')
            receipt = json.loads(raw)
            record = old.load(canonical=True)
            if record['phase'] != 'RELEASED' or record['target'] != 'INSTALLED':
                raise ValueError('Historical installation did not settle.')
            installer = existing.installer
            historical = {
                'maintenance_id': old.hold_id, 'project': str(old.project), 'source': record['target'],
                'source_manifest_sha256': old.manifest.sha256,
                'controller_journal_sha256': installer.digest(installer.encode(record)),
                'installer_receipt_sha256': installer.digest(installer.encode(record['receipt'])),
            }
            if historical != receipt['controller_terminal']:
                raise ValueError('Historical controller terminal differs from the approved -04 lineage.')
            transaction, _ = existing.read(existing.physical(old.state / installer.JOURNAL))
            if transaction != installer.encode({**record['receipt'], 'owners': old.manifest.owners}):
                raise ValueError('Historical installer transaction differs from its terminal receipt.')

            # The historical source layout still applies, with the single
            # explicitly measured -04 host version in its existing slot.
            host_mode, _ = old.manifest.after[HOST_RELATIVE]
            current = {**old.manifest.after, HOST_RELATIVE: (host_mode, receipt['after_sha256'])}
            if (old.verify_tree(record, current) != old.canonical
                    or any(existing.present(path) for path in (old.marker, old.units.sentinel))):
                raise ValueError('Current checkout or maintenance state differs from the restored baseline.')
            with installer.source_tree(old.project, False) as tree:
                directories = installer.source_directories(tree)
                with installer.directory(existing.gate.PARKED, tree['src']) as parked:
                    directories.update(installer.source_directories({'guard': parked}))
            if (directories != record['receipt']['source_directories']
                    or directories['guard']['identity'] != record['guard']):
                raise ValueError('Restored source directory or parked guard identity changed.')
            old.units.check_status(record['prior'], held=False, restored=True)
            if self.verify_host_exclusion() is not True:
                raise ValueError('Exclusive wrapper host scope was not verified.')
            yield {**historical, 'predecessor_receipt_sha256': FORWARD_RECEIPT_SHA256,
                   'historical_predecessor_receipt_sha256': historical['installer_receipt_sha256']}

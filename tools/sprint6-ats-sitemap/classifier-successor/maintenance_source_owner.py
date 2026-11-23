"""Join the native window to the individually approved source transition."""

from hashlib import sha256
from pathlib import Path

from job_search_helper import integration_release as release
from release_admission_bootstrap import _validate_runtime

import native_source_advance as source


class MaintenanceSourceOwner:
    def __init__(self, project, package, package_sha256):
        self.project = Path(project).resolve(strict=True)
        self.package = Path(package).resolve(strict=True)
        self.pin = package_sha256
        self.spec = source._read_spec(self.package, self.pin)
        self.manifest, self.manifest_pin, self.binding = source._binding(self.project, self.spec, self.pin)
        self.release_id = self.binding['release_id']
        self.state = self.project / '.state'
        self.journal = self.state / 'integration-release-journal.json'
        self.record = self.state / 'native-runtime-releases' / self.release_id

    def status(self):
        """Measure only the exact approved predecessor, successor or owned hold."""
        raw = self.journal.read_bytes()
        journal = release._read_json(self.journal)
        if sha256(raw).hexdigest() == self.spec['live_journal_sha256']:
            if _validate_runtime(self.project, self.state) != self.spec['live_runtime']:
                raise ValueError('The original admitted MuleLab source changed.')
            source._check_vectors(self.project, self.spec, 'before')
            phase = 'BEFORE'
        else:
            if (journal.get('kind') != 'native-source-maintenance' or journal.get('record') != str(self.record)
                    or journal.get('release_id') != self.release_id or journal.get('release') != self.binding
                    or journal.get('manifest_sha256') != self.manifest_pin
                    or release._read_json(self.record / 'manifest.json') != self.manifest
                    or release.metadata(self.record / 'prior-journal.json')['sha256'] != self.spec['live_journal_sha256']):
                raise ValueError('MuleLab points to a different source maintenance record.')
            if journal['state'] == 'COMPLETE':
                receipt = release._read_json(self.record / 'receipt.json')
                if (receipt != {'schema': 'native-source-maintenance-receipt-v1', 'state': 'COMPLETE',
                                'release_id': self.release_id, 'manifest_sha256': self.manifest_pin,
                                'release': self.binding}
                        or journal.get('receipt_sha256') != release.digest(receipt)
                        or _validate_runtime(self.project, self.state)['release_id'] != self.release_id):
                    raise ValueError('The new MuleLab source activation lacks its exact completion receipt.')
                source._check_vectors(self.project, self.spec, 'staged')
                phase = 'STAGED'
            elif journal['state'] == 'PREPARED':
                phase = 'PREPARED'
            else:
                raise ValueError('The maintenance record is in an unsupported state.')

        endpoints = {}
        for name, pair in self.spec['package_files'].items():
            actual = source._current_endpoint(self.project / name, pair['owner'])
            if actual not in (pair['before'], pair['staged']):
                raise ValueError('A source file changed outside the approved maintenance: ' + name)
            endpoints[name] = actual
        if self.journal.read_bytes() != raw:
            raise RuntimeError('The active MuleLab source record changed during verification.')
        return {'phase': phase, 'endpoints': endpoints, 'release_id': self.release_id,
                'manifest_sha256': self.manifest_pin, 'package_sha256': self.pin}

    def advance(self, *, check_idle):
        return source.advance(self.project, self.package, self.pin, check_idle=check_idle)

    def rollback_prepared(self):
        return source.rollback_prepared(self.project, self.package, self.pin)

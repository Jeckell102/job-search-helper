"""Read independently qualified automated releases from their owner directory."""

from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path

from . import private_file_custody as private
from .integration_release import canonical_manifest, digest


_SCHEMA = 'integration-live-release-qualification-v1'
_FIELDS = {
    'schema', 'result', 'evidence_class', 'release_qualification',
    'manifest_sha256', 'capture_manifest_sha256', 'candidate_validation_sha256',
    'reviewed_tools_sha256',
}
_MAX_RECEIPT_BYTES = 16 * 1024


def _is_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


class _QualificationOwner:
    def __init__(self, path, descriptor, root_identity, receipt_sha256):
        self._path = path
        self._descriptor = descriptor
        self._root_identity = root_identity
        self._receipt_sha256 = receipt_sha256

    def _check_root(self):
        if (self._descriptor < 0
                or private.directory(os.fstat(self._descriptor)) != self._root_identity
                or private.named_path_identity(self._path) != self._root_identity):
            raise ValueError('The release qualification directory is unavailable or was replaced')

    def require(self, manifest):
        self._check_root()
        manifest = canonical_manifest(manifest)
        name = manifest['release_id'] + '.json'
        try:
            raw, _, stamp = private.read_file(self._descriptor, name, _MAX_RECEIPT_BYTES)
        except (OSError, ValueError):
            raise ValueError('The owner-pinned release qualification receipt is unavailable') from None
        if sha256(raw).hexdigest() != self._receipt_sha256:
            raise ValueError('The owner-pinned release qualification receipt changed')
        receipt = private.decode(raw)
        if (set(receipt) != _FIELDS or receipt['schema'] != _SCHEMA
                or receipt['result'] != 'PASS' or receipt['evidence_class'] != 'live_normal_dispatch'
                or receipt['release_qualification'] is not True
                or receipt['manifest_sha256'] != digest(manifest)
                or receipt['candidate_validation_sha256'] != manifest['validation_receipt_sha256']
                or not _is_digest(receipt['capture_manifest_sha256'])
                or not _is_digest(receipt['reviewed_tools_sha256'])):
            raise ValueError('The exact candidate lacks independent live release qualification')
        private.named_file(self._descriptor, name, stamp)
        self._check_root()


@contextmanager
def open_release_qualification_owner(path, descriptor, *, expected_owner_identity, approved_receipt_sha256):
    """Use an already configured qualification owner and its approved exact bytes."""
    path = Path(path)
    if (not path.is_absolute() or path == Path('/') or '..' in path.parts
            or not isinstance(expected_owner_identity, (list, tuple)) or len(expected_owner_identity) != 2
            or any(type(number) is not int or number <= 0 for number in expected_owner_identity)
            or not _is_digest(approved_receipt_sha256)):
        raise ValueError('An independently configured release qualification owner is required')
    duplicate = os.dup(descriptor)
    owner = _QualificationOwner(path, duplicate, list(expected_owner_identity), approved_receipt_sha256)
    try:
        owner._check_root()
        yield owner
    finally:
        owner._descriptor = -1
        os.close(duplicate)

"""Read the approved live verdict for one already published dispatch."""

from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path

from . import ordinary_raw_capture as private
from .ordinary_verification_pending import _is_digest, digest
from .repository import RepositoryError


_SCHEMA = 'ordinary-live-mapping-verdict-v1'
_MACHINE_EVIDENCE = ('authority_extraction_digest', 'candidate_inventory_digest',
                     'regression_inventory_digest')
_EVIDENCE = ('live_capture_sha256', 'candidate_validation_sha256', *_MACHINE_EVIDENCE)
_FIELDS = {
    'schema', 'mode', 'result', 'application_authority', 'dispatch_sha256',
    'publication_sha256', 'verifier_input_sha256', 'raw_capture_manifest_sha256',
    'reviewed_tools_sha256', *_EVIDENCE,
}


class _LiveVerdictOwner:
    __slots__ = ('_path', '_directory', '_root_identity', '_approved_verdict_sha256', '_reviewed_tools_sha256')

    def __init__(self, path, directory, root_identity, verdict_sha, tools_sha):
        self._path = path
        self._directory = directory
        self._root_identity = root_identity
        self._approved_verdict_sha256 = verdict_sha
        self._reviewed_tools_sha256 = tools_sha

    def _check_root(self):
        try:
            opened = private._directory(os.fstat(self._directory))
            named = private._named_path_identity(self._path)
        except (OSError, ValueError):
            raise RepositoryError('The live verdict owner directory is unavailable.') from None
        if opened != self._root_identity or named != self._root_identity:
            raise RepositoryError('The live verdict owner directory changed.')

    def require(self, marker, publication, capture_manifest_sha):
        self._check_root()
        dispatch = marker['dispatch_sha256']
        if not _is_digest(dispatch) or not _is_digest(capture_manifest_sha):
            raise RepositoryError('The live verdict requires exact dispatch and response custody.')
        name = dispatch + '.json'
        try:
            raw, _, stamp = private._read_file(self._directory, name, 16 * 1024)
            if sha256(raw).hexdigest() != self._approved_verdict_sha256:
                raise RepositoryError('The approved live verdict changed.')
            verdict = private._decode(raw)
            private._named_file(self._directory, name, stamp)
        except (OSError, ValueError):
            raise RepositoryError('The owner-pinned live verdict is unavailable or malformed.') from None
        request = {key: marker[key] for key in ('schema', 'owner', 'admission', 'observation')}
        if (set(verdict) != _FIELDS or verdict['schema'] != _SCHEMA
                or verdict['mode'] != 'live_normal_dispatch'
                or verdict['result'] != 'VERIFIED_MISMATCH' or verdict['application_authority'] is not True
                or verdict['dispatch_sha256'] != dispatch
                or verdict['publication_sha256'] != digest(publication)
                or verdict['verifier_input_sha256'] != digest(request)
                or verdict['raw_capture_manifest_sha256'] != capture_manifest_sha
                or verdict['reviewed_tools_sha256'] != self._reviewed_tools_sha256
                or any(not _is_digest(verdict[key]) for key in _EVIDENCE)):
            raise RepositoryError('The result is not an exact approved live mapping verdict.')
        self._check_root()
        return ({key: verdict[key] for key in _MACHINE_EVIDENCE}, {
            'dispatch_sha256': dispatch, 'publication_sha256': verdict['publication_sha256'],
            'qualified_verdict_sha256': self._approved_verdict_sha256,
        })


@contextmanager
def open_live_mapping_verdict_owner(path, descriptor, *, expected_owner_identity,
                                    approved_verdict_sha256, reviewed_tools_sha256):
    """Open the configured live qualification authority, never an offline work slot."""
    path = Path(path)
    if (not path.is_absolute() or path == Path('/') or '..' in path.parts
            or not isinstance(expected_owner_identity, (tuple, list)) or len(expected_owner_identity) != 2
            or any(type(part) is not int or part <= 0 for part in expected_owner_identity)
            or not _is_digest(approved_verdict_sha256) or not _is_digest(reviewed_tools_sha256)):
        raise ValueError('An independently configured live verdict owner is required.')
    directory = os.dup(descriptor)
    owner = _LiveVerdictOwner(path, directory, list(expected_owner_identity),
                              approved_verdict_sha256, reviewed_tools_sha256)
    try:
        owner._check_root()
        yield owner
    finally:
        owner._directory = -1
        os.close(directory)

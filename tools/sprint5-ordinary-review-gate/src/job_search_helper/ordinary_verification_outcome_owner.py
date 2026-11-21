"""Reserve the first outcome before an ordinary verification attempt is armed."""

from . import ordinary_verification_pending as pending
from .ordinary_verification_outcome import existing_outcome
from .repository import RepositoryError
from .runtime_mapping_facts import _store_identity


_TABLE = 'ordinary_verification_outcome_owners'
_SCOPE = ('cycle_id', 'request_id', 'company_id', 'source_revision')
_FIELDS = (*_SCOPE, 'dispatch_sha256', 'state_path', 'state_device', 'state_inode')


def _has_reservations(db):
    return db.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?", (_TABLE,),
    ).fetchone() is not None


def _binding(stores, scope, dispatch_sha256):
    try:
        _store_identity(stores.jobs, stores.jobs.db)
        state_path, (device, inode) = _store_identity(stores.state, stores.state.connection)
    except (OSError, ValueError) as exc:
        raise RepositoryError('Ordinary outcome ownership lost its managed State or Jobs.') from exc
    return dict(zip(_FIELDS, (*scope, dispatch_sha256, str(state_path), device, inode)))


def reserve_outcome_owner(stores, owner, dispatch_sha256):
    """Commit exact Jobs ownership before the caller writes its State marker.

    The measured caller owns the scraper and writer leases and passes idle
    descriptor-bound stores with writable Jobs. An existing canonical outcome
    wins without creating a reservation. A retry can resume only the exact
    saved reservation, including its original State inode and dispatch.
    """
    if (not isinstance(owner, dict)
            or any(not isinstance(owner.get(key), str) or not owner[key]
                   or len(owner[key]) > 256
                   or owner[key] != owner[key].strip() for key in _SCOPE)
            or not pending._is_digest(owner.get('source_revision'))
            or not pending._is_digest(owner.get('store_binding_sha256'))
            or not pending._is_digest(dispatch_sha256)):
        raise RepositoryError('Malformed ordinary outcome ownership.')
    pending._check_stores(stores, owner)
    jobs = stores.jobs
    scope = tuple(owner[key] for key in _SCOPE)
    binding = _binding(stores, scope, dispatch_sha256)
    with jobs.transaction():
        saved = _read_reservation(jobs.db, owner['cycle_id'], owner['company_id'])
        if saved is not None and saved != binding:
            raise RepositoryError('Ordinary outcome ownership belongs to another dispatch or State.')
        prior = existing_outcome(jobs, owner)
        if _binding(stores, scope, dispatch_sha256) != binding:
            raise RepositoryError('Ordinary outcome ownership changed during reservation.')
        if prior is None and saved is None:
            _insert_reservation(jobs.db, binding)
    pending._check_stores(stores, owner)
    if prior is not None:
        return {'state': 'EXISTING_OUTCOME', 'outcome': prior}
    if _read_reservation(jobs.db, owner['cycle_id'], owner['company_id']) != binding:
        raise RepositoryError('The committed ordinary outcome reservation did not read back exactly.')
    return {'state': 'RESERVED', 'owner': binding}


def require_reserved_outcome_owner(stores, owner, dispatch_sha256):
    """Compare the committed Jobs reservation with the same managed owner."""
    pending._check_stores(stores, owner)
    scope = tuple(owner[key] for key in _SCOPE)
    expected = _binding(stores, scope, dispatch_sha256)
    actual = _read_reservation(stores.jobs.db, owner['cycle_id'], owner['company_id'])
    if actual != expected:
        raise RepositoryError('The verification dispatch has no matching committed outcome reservation.')
    return actual


def _read_reservation(db, cycle_id, company_id):
    if not _has_reservations(db):
        return None
    row = db.execute(
        f"SELECT {', '.join(_FIELDS)} FROM main.{_TABLE} WHERE cycle_id=? AND company_id=?",
        (cycle_id, company_id),
    ).fetchone()
    return dict(zip(_FIELDS, row)) if row is not None else None


def _insert_reservation(db, binding):
    db.execute(f"""CREATE TABLE IF NOT EXISTS main.{_TABLE} (
        cycle_id TEXT NOT NULL, request_id TEXT NOT NULL, company_id TEXT NOT NULL,
        source_revision TEXT NOT NULL, dispatch_sha256 TEXT NOT NULL,
        state_path TEXT NOT NULL, state_device INTEGER NOT NULL, state_inode INTEGER NOT NULL,
        PRIMARY KEY (cycle_id, company_id)
    ) WITHOUT ROWID""")
    db.execute(f"""CREATE INDEX IF NOT EXISTS main.{_TABLE}_request
        ON {_TABLE}(request_id, company_id, source_revision)""")
    db.execute(
        f"INSERT INTO main.{_TABLE} ({', '.join(_FIELDS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(binding[key] for key in _FIELDS),
    )


def has_reserved_outcome(db, cycle_id=None):
    """Read Jobs ownership even if arming State was interrupted."""
    if not _has_reservations(db):
        return False
    if cycle_id is None:
        return db.execute(f'SELECT 1 FROM main.{_TABLE} LIMIT 1').fetchone() is not None
    return db.execute(f'SELECT 1 FROM main.{_TABLE} WHERE cycle_id=? LIMIT 1',
                      (cycle_id,)).fetchone() is not None


def reserved_outcome_companies(db, cycle_id):
    """List the reserved Companies for one cycle for local review readback."""
    if not _has_reservations(db):
        return ()
    return tuple(
        company_id for (company_id,) in db.execute(
            f'SELECT company_id FROM main.{_TABLE} WHERE cycle_id=? ORDER BY company_id',
            (cycle_id,),
        )
    )


def assert_outcome_unreserved(db, identity, *, facts=None, classification=None):
    """Fence public writes as part of the existing Jobs transaction."""
    if not _has_reservations(db):
        return
    cycle_id = identity.get('cycle_id')
    if cycle_id:
        reserved = _read_reservation(db, cycle_id, identity['company_id'])
    else:
        reserved = db.execute(
            f'SELECT 1 FROM main.{_TABLE} WHERE request_id=? AND company_id=? AND source_revision=? LIMIT 1',
            tuple(identity[key] for key in _SCOPE[1:]),
        ).fetchone()
    if reserved is not None:
        from .ordinary_verification_finisher import permits_published_outcome_write
        if not permits_published_outcome_write(db, identity, facts, classification, reserved):
            raise RepositoryError('Enrolled ordinary outcomes require their exact verification finisher.')

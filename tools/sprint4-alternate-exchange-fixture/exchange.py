"""Linux directory exchange rehearsal restricted to this module's private fixtures."""
from contextlib import ExitStack, contextmanager
import ctypes
from dataclasses import dataclass
import errno
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4


LANE = Path(__file__).absolute().parent
JOURNAL = 'exchange.json'
LOCK = 'exchange.lock'
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
REGULAR = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
SCHEMA = 'fixture-checkout-exchange-v1'
PARK_PREFIX = '.exchange-park-'


class Hold(RuntimeError):
    """The controller cannot authorize the next transition."""


@dataclass(frozen=True)
class ExchangeProof:
    generation: str
    intent_sha256: str
    phase: str


def require(condition, message):
    if not condition:
        raise Hold(message)


def mount_id(fd):
    for line in Path(f'/proc/self/fdinfo/{fd}').read_text().splitlines():
        if line.startswith('mnt_id:'):
            return int(line.split()[1])
    raise Hold('cannot read mount identity')


def identity(fd):
    info = os.fstat(fd)
    return [info.st_dev, info.st_ino, mount_id(fd), info.st_uid, info.st_gid,
            stat.S_IMODE(info.st_mode)]


def private_file(fd):
    info = os.fstat(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
            'unsafe control file')


def missing(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return True
    return False


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def exchange(left, left_name, right, right_name):
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise Hold('renameat2 is unavailable') from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(left, os.fsencode(left_name), right, os.fsencode(right_name), 2):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


class FixtureExchange:
    """Accepts explicit paths only under LANE/fixtures/<fixture>."""

    def __init__(self, root, pairs):
        self.root = Path(root)
        self.pairs = tuple((Path(left), Path(right)) for left, right in pairs)
        require(LANE.parent == Path('/tmp') and LANE.name.startswith('jsh-s4-alternate-exchange.')
                and LANE.resolve() == LANE and self.root.parent == LANE / 'fixtures'
                and self.root.name not in ('', '.', '..'), 'fixture is outside the private lane')
        require(bool(self.pairs), 'no fixture pairs')
        for left, right in self.pairs:
            require(left.parent == right.parent == self.root / 'checkouts'
                    and left.name not in ('', '.', '..') and not left.name.startswith(PARK_PREFIX)
                    and right.name.startswith(PARK_PREFIX) and right.name != PARK_PREFIX,
                    'endpoint is outside its fixture parent')
        require(len(set(sum(self.pairs, ()))) == 2 * len(self.pairs), 'duplicate fixture endpoint')

    @contextmanager
    def _open(self, *, write, initialize=False):
        try:
            with ExitStack() as stack:
                def directory(name, parent=None):
                    handle = os.open(name, DIRECTORY, dir_fd=parent)
                    stack.callback(os.close, handle)
                    return handle

                lane = directory(LANE)
                fixtures = directory('fixtures', lane)
                root = directory(self.root.name, fixtures)
                checkouts = directory('checkouts', root)
                control = directory('control', root)
                parents = [identity(fd) for fd in (lane, fixtures, root, checkouts, control)]
                require(all(pin[3] == os.geteuid() and pin[5] == 0o700 for pin in parents),
                        'fixture parents must be private and caller-owned')
                require(len({(pin[0], pin[2]) for pin in parents}) == 1, 'fixture spans mounts')
                require(len({(pin[0], pin[1]) for pin in parents}) == len(parents), 'aliased fixture parent')
                self._check_mounts()
                flags = os.O_RDWR if write else os.O_RDONLY
                if initialize:
                    flags |= os.O_CREAT | os.O_EXCL
                lock = os.open(LOCK, flags | REGULAR, 0o600, dir_fd=control)
                stack.callback(os.close, lock)
                private_file(lock)
                fcntl.flock(lock, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                lock_pin = identity(lock)
                require((lock_pin[0], lock_pin[2]) == (parents[-1][0], parents[-1][2]),
                        'control lock spans mounts')
                yield checkouts, control, [*parents, lock_pin]
        except OSError as error:
            if error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise Hold('fixture exchange is busy') from None
            raise Hold(f'fixture filesystem check failed (errno {error.errno})') from None

    def _check_mounts(self):
        for line in Path('/proc/self/mountinfo').read_bytes().splitlines():
            field = line.split()[4]
            path = Path(os.fsdecode(re.sub(rb'\\([0-7]{3})',
                                          lambda match: bytes([int(match[1], 8)]), field)))
            require(not (path == self.root or self.root in path.parents),
                    'mount at or below fixture root')

    @contextmanager
    def _endpoint(self, fd, name):
        endpoint = os.open(name, DIRECTORY, dir_fd=fd)
        try:
            pin = identity(endpoint)
            parent_pin = identity(fd)
            require(pin[0] == parent_pin[0] and pin[2] == parent_pin[2]
                    and pin[3] == os.geteuid(), 'endpoint owner or mount differs')
            yield endpoint, pin
        finally:
            os.close(endpoint)

    def _persist(self, control, journal):
        temporary = f'.exchange-{uuid4().hex}.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | REGULAR,
                     0o600, dir_fd=control)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encode(journal))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, JOURNAL, src_dir_fd=control, dst_dir_fd=control)
        os.fsync(control)

    def _load(self, control, parents):
        fd = os.open(JOURNAL, os.O_RDONLY | REGULAR, dir_fd=control)
        with os.fdopen(fd, 'rb') as stream:
            private_file(stream.fileno())
            try:
                journal = json.load(stream)
                intent = journal['intent']
                names = [(left.name, right.name) for left, right in self.pairs]
                require(intent['schema'] == SCHEMA and intent['root'] == str(self.root)
                        and intent['parents'] == parents
                        and [tuple(pair['names']) for pair in intent['pairs']] == names
                        and re.fullmatch('[a-f0-9]{32}', intent['generation'])
                        and sha256(encode(intent)).hexdigest() == journal['intent_sha256'],
                        'journal does not match pinned fixture')
                phase, count = journal['phase'], journal['completed']
                require(type(count) is int and 0 <= count <= len(names), 'invalid exchange progress')
                proof = journal['terminal_proof_sha256']
                require((phase in ('closing', 'closed') and proof is None)
                        or (phase in ('restoring', 'restored') and re.fullmatch('[a-f0-9]{64}', proof)),
                        'invalid exchange phase or proof')
                require(phase not in ('closed', 'restored') or count == len(names),
                        'incomplete terminal exchange phase')
                return journal
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise Hold('invalid exchange journal') from None

    def prepare(self):
        """Seal all pairs before any exchange. Each sentinel must already exist and be empty."""
        with self._open(write=True, initialize=True) as (parent, control, parents):
            require(missing(control, JOURNAL), 'exchange journal already exists')
            pairs = []
            for left, right in self.pairs:
                with self._endpoint(parent, left.name) as (_, original):
                    with self._endpoint(parent, right.name) as (empty, sentinel):
                        require(sentinel[5] == 0o500 and not os.listdir(empty), 'sentinel is not empty and sealed')
                        os.fsync(empty)
                pairs.append(dict(names=[left.name, right.name], original=original, sentinel=sentinel))
            endpoints = [tuple(pair[role][:2]) for pair in pairs for role in ('original', 'sentinel')]
            require(len(set(endpoints)) == len(endpoints), 'aliased fixture endpoint')
            os.fsync(parent)
            intent = dict(schema=SCHEMA, generation=uuid4().hex, root=str(self.root), parents=parents, pairs=pairs)
            journal = dict(intent=intent, intent_sha256=sha256(encode(intent)).hexdigest(),
                           phase='closing', completed=0, terminal_proof_sha256=None)
            self._persist(control, journal)

    def _placements(self, parent, journal):
        self._check_mounts()
        placements = []
        for pair in journal['intent']['pairs']:
            left, right = pair['names']
            with self._endpoint(parent, left) as (left_dir, left_pin):
                with self._endpoint(parent, right) as (right_dir, right_pin):
                    if (left_pin, right_pin) == (pair['original'], pair['sentinel']):
                        sentinel, closed = right_dir, False
                    elif (left_pin, right_pin) == (pair['sentinel'], pair['original']):
                        sentinel, closed = left_dir, True
                    else:
                        raise Hold('absent or substituted pinned endpoint')
                    require(not os.listdir(sentinel), 'pinned sentinel is occupied')
                    placements.append(closed)
        return placements

    @staticmethod
    def _proof(journal, phase):
        return ExchangeProof(journal['intent']['generation'], journal['intent_sha256'], phase)

    def _advance(self, parent, control, journal, *, close):
        phase = 'closed' if close else 'restored'
        count = journal['completed']
        length = len(self.pairs)

        def prefix(done):
            return [close] * done + [not close] * (length - done)

        # The preceding process may have died after journal replace and before fsync.
        os.fsync(control)
        observed = self._placements(parent, journal)
        if count < length and observed == prefix(count + 1):
            os.fsync(parent)
            count += 1
            journal['completed'] = count
            self._persist(control, journal)
        else:
            require(observed == prefix(count), 'placements disagree with durable phase or next swap')
        while count < length:
            require(self._placements(parent, journal) == prefix(count), 'endpoint changed before swap')
            left, right = journal['intent']['pairs'][count]['names']
            # Keep both names under one parent so the read-only sentinel keeps its mode.
            exchange(parent, left, parent, right)
            os.fsync(parent)
            count += 1
            require(self._placements(parent, journal) == prefix(count), 'endpoint changed after swap')
            journal['completed'] = count
            self._persist(control, journal)
        if journal['phase'] != phase:
            journal['phase'] = phase
            self._persist(control, journal)
        return self._proof(journal, phase)

    def close(self):
        with self._open(write=True) as (parent, control, parents):
            journal = self._load(control, parents)
            require(journal['phase'] in ('closing', 'closed'), 'exchange is past closure')
            return self._advance(parent, control, journal, close=True)

    def restore(self, evidence, *, verify_terminal):
        """Require the external verifier for entry and every restore replay."""
        require(type(evidence) is bytes and bool(evidence), 'terminal evidence is required')
        evidence_hash = sha256(evidence).hexdigest()
        with self._open(write=True) as (parent, control, parents):
            journal = self._load(control, parents)
            phase = journal['phase']
            require(phase in ('closed', 'restoring', 'restored'), 'closure incomplete')
            if phase == 'closed':
                require(all(self._placements(parent, journal)), 'closure incomplete')
            else:
                require(evidence_hash == journal['terminal_proof_sha256'], 'terminal evidence changed')
            require(verify_terminal(self._proof(journal, 'closed'), evidence) is True,
                    'external terminal proof refused')
            if phase == 'closed':
                journal.update(phase='restoring', completed=0, terminal_proof_sha256=evidence_hash)
                self._persist(control, journal)
            return self._advance(parent, control, journal, close=False)

    def witness(self, phase):
        """Read-only endpoint/journal attestation. The caller owns route drain evidence."""
        require(phase in ('closed', 'restored'), 'unknown witness phase')
        with self._open(write=False) as (parent, control, parents):
            journal = self._load(control, parents)
            require(journal['phase'] == phase, 'durable witness phase differs')
            require(self._placements(parent, journal) == [phase == 'closed'] * len(self.pairs),
                    'witness placements differ')
            return self._proof(journal, phase)

"""Policy-pinned Linux checkout exchange. Importing this module takes no action."""
from contextlib import ExitStack, contextmanager
import ctypes
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import fcntl
from uuid import uuid4


FIXTURE_BASE = Path(__file__).absolute().parent / 'fixtures'
POLICY_SCHEMA = 'alternate-checkout-exchange-policy-v1'
JOURNAL_SCHEMA = 'alternate-checkout-exchange-journal-v1'
LOCK = 'exchange.lock'
JOURNAL = 'exchange.json'
POLICY = 'policy.json'
CLOSED_ACKNOWLEDGED = 'closed-acknowledged'
PARK_PREFIX = '.exchange-park-'
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
HEX = re.compile('[a-f0-9]{64}')
MAX_RECORD = 256 * 1024


class Hold(RuntimeError):
    """No exchange transition is authorized."""


@dataclass(frozen=True)
class Pin:
    device: int
    inode: int
    mount_id: int
    uid: int
    gid: int
    mode: int


@dataclass(frozen=True)
class Pair:
    parent: Path
    canonical: Path
    parked: Path
    parent_pin: Pin
    original_pin: Pin
    sentinel_pin: Pin


@dataclass(frozen=True)
class ExchangePolicy:
    mode: str
    generation: str
    mount_namespace: str
    control: Path
    control_pin: Pin
    lock_pin: Pin
    pairs: tuple[Pair, ...]
    sha256: str


@dataclass(frozen=True)
class ExchangeWitness:
    generation: str
    intent_sha256: str
    policy_sha256: str
    phase: str
    mount_namespace: str
    control: Path
    control_pin: Pin
    lock: Path
    lock_pin: Pin
    pairs: tuple[Pair, ...]
    terminal_proof_sha256: str | None


def require(ok, message):
    if not ok:
        raise Hold(message)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, 'duplicate record field')
        result[name] = value
    return result


def _read_object(fd):
    with os.fdopen(fd, 'rb') as stream:
        private_file(stream.fileno())
        data = stream.read(MAX_RECORD + 1)
    require(len(data) <= MAX_RECORD, 'control record too large')
    return data, json.loads(data, object_pairs_hook=unique_fields)


def mount_id(fd):
    for line in Path(f'/proc/self/fdinfo/{fd}').read_text().splitlines():
        if line.startswith('mnt_id:'):
            return int(line.split()[1])
    raise Hold('cannot read mount identity')


def pin(fd):
    info = os.fstat(fd)
    return Pin(info.st_dev, info.st_ino, mount_id(fd), info.st_uid, info.st_gid,
               stat.S_IMODE(info.st_mode))


def private_file(fd):
    info = os.fstat(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
            'unsafe private control file')


def _path(value):
    result = Path(value)
    require(result.is_absolute() and str(result) == value and '..' not in result.parts
            and result.anchor == '/' and result != Path('/'), 'expected exact absolute path')
    return result


def _name(value):
    require(isinstance(value, str) and 0 < len(value) <= 255
            and value not in ('.', '..') and '/' not in value and '\0' not in value,
            'expected exact pathname component')
    return value


def _policy_pin(value):
    keys = {member.name for member in fields(Pin)}
    require(isinstance(value, dict) and value.keys() == keys
            and all(type(number) is int and number >= 0 for number in value.values()),
            'invalid filesystem pin')
    return Pin(**value)


@contextmanager
def _directory(path):
    """Open each component relative to its physically opened parent."""
    fd = os.open('/', DIRECTORY)
    try:
        for name in path.parts[1:]:
            child = os.open(name, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _guard_errors():
    try:
        yield
    except (OSError, ValueError, TypeError, KeyError) as exc:
        error_number = getattr(exc, 'errno', None)
        detail = f' with errno {error_number}' if error_number is not None else ''
        raise Hold(f'exchange evidence unavailable ({type(exc).__name__}{detail})') from None


def load_policy(path, approved_sha256):
    """Authenticate the named private policy against an independently trusted digest."""
    with _guard_errors():
        path = _path(os.fspath(path))
        require(path.name == POLICY and HEX.fullmatch(approved_sha256), 'invalid approval pin')
        with _directory(path.parent) as directory:
            fd = os.open(path.name, os.O_RDONLY | FILE, dir_fd=directory)
            data, raw = _read_object(fd)
            require(sha256(data).hexdigest() == approved_sha256, 'policy seal mismatch')
            require(set(raw) == {'schema', 'mode', 'generation', 'mount_namespace', 'control',
                                 'control_pin', 'lock_pin', 'pairs'}
                    and raw['schema'] == POLICY_SCHEMA
                    and raw['mode'] in ('fixture', 'host')
                    and re.fullmatch('[a-f0-9]{32}', raw['generation'])
                    and re.fullmatch(r'mnt:\[\d+\]', raw['mount_namespace']),
                    'invalid exchange policy')
            control = _path(raw['control'])
            control_pin = _policy_pin(raw['control_pin'])
            lock_pin = _policy_pin(raw['lock_pin'])
            require(control == path.parent and pin(directory) == control_pin
                    and control_pin.mode == 0o700 and lock_pin.mode == 0o600, 'unexpected control location')
        require(isinstance(raw['pairs'], list) and bool(raw['pairs']), 'empty exchange policy')
        pairs = []
        for raw_pair in raw['pairs']:
            require(set(raw_pair) == {'parent', 'canonical', 'parked', 'parent_pin',
                                      'original_pin', 'sentinel_pin'}, 'invalid exchange pair')
            parent = _path(raw_pair['parent'])
            canonical, parked = _name(raw_pair['canonical']), _name(raw_pair['parked'])
            require(not canonical.startswith(PARK_PREFIX) and parked.startswith(PARK_PREFIX)
                    and parked != PARK_PREFIX, 'invalid same-parent alternate names')
            parent_pin, original, sentinel = (_policy_pin(raw_pair[key]) for key in
                                               ('parent_pin', 'original_pin', 'sentinel_pin'))
            require(sentinel.mode == 0o500 and parent_pin.mode & 0o300 == 0o300,
                    'invalid parent or sentinel permissions')
            pairs.append(Pair(parent, parent / canonical, parent / parked, parent_pin, original, sentinel))
        policy = ExchangePolicy(raw['mode'], raw['generation'], raw['mount_namespace'], control,
                                control_pin, lock_pin, tuple(pairs), approved_sha256)
        _validate_policy(policy)
        return policy


def _validate_policy(policy):
    parents = {}
    endpoints = {}
    for pair in policy.pairs:
        prior = parents.setdefault(pair.parent, pair.parent_pin)
        require(prior == pair.parent_pin, 'conflicting parent pins')
        for path, expected in ((pair.canonical, pair.original_pin), (pair.parked, pair.sentinel_pin)):
            require(path not in endpoints, 'reused endpoint')
            endpoints[path] = expected
    require(all(path != policy.control and path not in policy.control.parents
                and policy.control not in path.parents
                and not any(path == parent or path in parent.parents for parent in parents)
                for path in endpoints), 'endpoint overlaps another policy path')
    require(all(path != policy.control and policy.control not in path.parents for path in parents),
            'controlled parent overlaps control directory')
    locations = [*parents.values(), *endpoints.values(), policy.control_pin, policy.lock_pin]
    require(len({(item.device, item.inode) for item in locations}) == len(locations),
            'duplicate pinned inode')
    require(all((item.device, item.mount_id, item.uid) ==
                (policy.control_pin.device, policy.control_pin.mount_id, os.geteuid())
                for item in locations), 'policy owner or mount differs')
    if policy.mode == 'fixture':
        root = next((ancestor for ancestor in policy.control.parents if ancestor.parent == FIXTURE_BASE), None)
        require(root is not None and all(root in parent.parents for parent in parents),
                'fixture policy is outside the private lane')


def _exchange(parent, canonical, parked):
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise Hold('renameat2 unavailable') from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(canonical), parent, os.fsencode(parked), 2):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


class HostExchange:
    def __init__(self, policy_path, approved_sha256, *, enable_host_writes=False):
        self.policy_path = Path(policy_path)
        self.approved_sha256 = approved_sha256
        self._enable_host_writes = enable_host_writes

    @contextmanager
    def _open(self, *, write):
        with _guard_errors(), ExitStack() as opened:
            policy = load_policy(self.policy_path, self.approved_sha256)
            require(not write or policy.mode == 'fixture' or self._enable_host_writes is True,
                    'host mutations are disabled')
            control = opened.enter_context(_directory(policy.control))
            require(pin(control) == policy.control_pin, 'control directory changed')
            access = os.O_RDWR if write else os.O_RDONLY
            lock = os.open(LOCK, access | FILE, dir_fd=control)
            opened.callback(os.close, lock)
            private_file(lock)
            require(pin(lock) == policy.lock_pin, 'control lock changed')
            fcntl.flock(lock, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            parents = {}
            for pair in policy.pairs:
                if pair.parent not in parents:
                    parents[pair.parent] = opened.enter_context(_directory(pair.parent))
                require(pin(parents[pair.parent]) == pair.parent_pin, 'approved parent changed')
            self._verify_anchors(policy)
            yield policy, control, parents

    @staticmethod
    def _verify_anchors(policy):
        require(os.readlink('/proc/self/ns/mnt') == policy.mount_namespace, 'mount namespace changed')
        with _directory(policy.control) as control:
            require(pin(control) == policy.control_pin, 'canonical control directory changed')
            lock = os.open(LOCK, os.O_RDONLY | FILE, dir_fd=control)
            try:
                private_file(lock)
                require(pin(lock) == policy.lock_pin, 'canonical control lock changed')
            finally:
                os.close(lock)
        unique_parents = {pair.parent: pair.parent_pin for pair in policy.pairs}
        for path, expected in unique_parents.items():
            with _directory(path) as parent:
                require(pin(parent) == expected, 'canonical approved parent changed')
        endpoints = {path for pair in policy.pairs for path in (pair.canonical, pair.parked)}
        for line in Path('/proc/self/mountinfo').read_bytes().splitlines():
            target = Path(os.fsdecode(re.sub(rb'\\([0-7]{3})',
                                             lambda match: bytes([int(match[1], 8)]), line.split()[4])))
            require(target not in endpoints and endpoints.isdisjoint(target.parents)
                    and target != policy.control / JOURNAL, 'mount crosses an exchange endpoint or journal')

    @staticmethod
    def _placements(policy, parents):
        HostExchange._verify_anchors(policy)
        positions = []
        for pair in policy.pairs:
            with ExitStack() as opened:
                descriptors = []
                for path in (pair.canonical, pair.parked):
                    fd = os.open(path.name, DIRECTORY, dir_fd=parents[pair.parent])
                    opened.callback(os.close, fd)
                    descriptors.append(fd)
                observed = tuple(pin(fd) for fd in descriptors)
                if observed == (pair.original_pin, pair.sentinel_pin):
                    closed, sentinel = False, descriptors[1]
                elif observed == (pair.sentinel_pin, pair.original_pin):
                    closed, sentinel = True, descriptors[0]
                else:
                    raise Hold('substituted exchange endpoint')
                require(not os.listdir(sentinel), 'pinned sentinel is occupied')
                positions.append(closed)
        return positions

    @staticmethod
    def _intent(policy):
        entries = [{
            'parent': str(pair.parent), 'canonical': str(pair.canonical), 'parked': str(pair.parked),
            'parent_pin': asdict(pair.parent_pin), 'original_pin': asdict(pair.original_pin),
            'sentinel_pin': asdict(pair.sentinel_pin),
        } for pair in policy.pairs]
        return dict(schema=JOURNAL_SCHEMA, generation=policy.generation, policy_sha256=policy.sha256,
                    mount_namespace=policy.mount_namespace, control=str(policy.control),
                    control_pin=asdict(policy.control_pin), lock_pin=asdict(policy.lock_pin), pairs=entries)

    @staticmethod
    def _persist(control, journal):
        temporary = f'.exchange-{uuid4().hex}.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | FILE, 0o600, dir_fd=control)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encode(journal))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, JOURNAL, src_dir_fd=control, dst_dir_fd=control)
        os.fsync(control)

    def _journal(self, policy, control):
        fd = os.open(JOURNAL, os.O_RDONLY | FILE, dir_fd=control)
        _, journal = _read_object(fd)
        intent = self._intent(policy)
        require(set(journal) == {'intent', 'intent_sha256', 'phase', 'completed', 'terminal_proof_sha256'}
                and journal['intent'] == intent and journal['intent_sha256'] == sha256(encode(intent)).hexdigest(),
                'journal is outside the approved generation')
        phase, count, proof = (journal[key] for key in ('phase', 'completed', 'terminal_proof_sha256'))
        require(type(count) is int and 0 <= count <= len(policy.pairs)
                and (phase not in ('closed', CLOSED_ACKNOWLEDGED, 'restored') or count == len(policy.pairs)),
                'invalid exchange progress')
        require((phase in ('closing', 'closed', CLOSED_ACKNOWLEDGED) and proof is None)
                or (phase in ('restoring', 'restored') and HEX.fullmatch(proof)), 'invalid phase or terminal proof')
        return journal

    def prepare(self):
        """Record all exchange intent without creating a sentinel, a lock or a hold."""
        with self._open(write=True) as (policy, control, parents):
            try:
                os.stat(JOURNAL, dir_fd=control, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                journal = self._journal(policy, control)
                require(journal['phase'] == 'closing' and journal['completed'] == 0
                        and not any(self._placements(policy, parents)), 'existing exchange has advanced')
                os.fsync(control)
                return journal['intent_sha256']
            require(not any(self._placements(policy, parents)), 'fixture or host already has swapped paths')
            for pair in policy.pairs:
                sentinel = os.open(pair.parked.name, DIRECTORY, dir_fd=parents[pair.parent])
                try:
                    require(pin(sentinel) == pair.sentinel_pin and not os.listdir(sentinel),
                            'sentinel changed during preparation')
                    os.fsync(sentinel)
                finally:
                    os.close(sentinel)
            for parent in parents.values():
                os.fsync(parent)
            intent = self._intent(policy)
            digest = sha256(encode(intent)).hexdigest()
            self._persist(control, dict(intent=intent, intent_sha256=digest, phase='closing', completed=0,
                                        terminal_proof_sha256=None))
            return digest

    @staticmethod
    def _witness(policy, journal, phase):
        return ExchangeWitness(policy.generation, journal['intent_sha256'], policy.sha256, phase,
                               policy.mount_namespace, policy.control, policy.control_pin, policy.control / LOCK,
                               policy.lock_pin, policy.pairs, journal['terminal_proof_sha256'])

    def _advance(self, policy, control, parents, journal, *, close):
        count, length = journal['completed'], len(policy.pairs)

        def prefix(done):
            return [close] * done + [not close] * (length - done)

        # Re-establish the journal directory sync after an interrupted replace.
        os.fsync(control)
        observed = self._placements(policy, parents)
        if count < length and observed == prefix(count + 1):
            os.fsync(parents[policy.pairs[count].parent])
            require(self._placements(policy, parents) == observed, 'placement changed during replay')
            count += 1
            journal['completed'] = count
            self._persist(control, journal)
        else:
            require(observed == prefix(count), 'placements disagree with journal or its single next swap')
        while count < length:
            require(self._placements(policy, parents) == prefix(count), 'placement changed before swap')
            pair = policy.pairs[count]
            parent = parents[pair.parent]
            _exchange(parent, pair.canonical.name, pair.parked.name)
            os.fsync(parent)
            count += 1
            require(self._placements(policy, parents) == prefix(count), 'placement changed after swap')
            journal['completed'] = count
            self._persist(control, journal)

    def close(self):
        with self._open(write=True) as (policy, control, parents):
            journal = self._journal(policy, control)
            require(journal['phase'] in ('closing', 'closed', CLOSED_ACKNOWLEDGED), 'exchange is past closure')
            self._advance(policy, control, parents, journal, close=True)
            if journal['phase'] == 'closing':
                journal['phase'] = 'closed'
                self._persist(control, journal)
            if journal['phase'] == 'closed':
                # The closure synced above, or was synced at the start of replay.
                # Only now may a read-only caller rely on an observed acknowledgment.
                journal['phase'] = CLOSED_ACKNOWLEDGED
                self._persist(control, journal)
            return self._witness(policy, journal, 'closed')

    def restore(self, evidence, *, verify_terminal):
        require(type(evidence) is bytes and bool(evidence), 'terminal proof required')
        digest = sha256(evidence).hexdigest()
        with self._open(write=True) as (policy, control, parents):
            journal = self._journal(policy, control)
            phase = journal['phase']
            require(phase in (CLOSED_ACKNOWLEDGED, 'restoring', 'restored'), 'closure is incomplete')
            if phase == CLOSED_ACKNOWLEDGED:
                require(all(self._placements(policy, parents)), 'closure is incomplete')
            else:
                require(journal['terminal_proof_sha256'] == digest, 'terminal proof changed')
            closed = self._witness(policy, {**journal, 'terminal_proof_sha256': None}, 'closed')
            require(verify_terminal(closed, evidence) is True, 'terminal proof refused')
            if phase == CLOSED_ACKNOWLEDGED:
                journal.update(phase='restoring', completed=0, terminal_proof_sha256=digest)
                self._persist(control, journal)
            self._advance(policy, control, parents, journal, close=False)
            if journal['phase'] != 'restored':
                journal['phase'] = 'restored'
                self._persist(control, journal)
            return self._witness(policy, journal, 'restored')

    def witness(self, phase='closed'):
        require(phase in ('closed', 'restored'), 'invalid witness phase')
        with self._open(write=False) as (policy, control, parents):
            journal = self._journal(policy, control)
            expected = CLOSED_ACKNOWLEDGED if phase == 'closed' else phase
            require(journal['phase'] == expected, 'requested witness phase is not durable')
            require(self._placements(policy, parents) == [phase == 'closed'] * len(policy.pairs),
                    'witness placement mismatch')
            return self._witness(policy, journal, phase)

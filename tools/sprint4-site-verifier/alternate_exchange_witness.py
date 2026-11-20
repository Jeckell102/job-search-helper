"""Verify a separately authorized, already closed alternate-checkout exchange."""
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from alternate_writer_witness import file_mount_id, mount_path


DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


@dataclass(frozen=True)
class ExchangeFence:
    parent: Path
    control: Path
    namespace: tuple[int, int]
    generation: str
    intent_sha256: str
    intent_schema: str
    launch_uid: int
    parent_identity: tuple[int, ...]
    control_identity: tuple[int, ...]
    lock_identity: tuple[int, ...]
    pairs: tuple[tuple[str, str], ...]

    def active_roots(self):
        return {self.parent / left for left, _ in self.pairs}

    def parked_roots(self):
        return {self.parent / right for _, right in self.pairs}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def directory_identity(descriptor):
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino, file_mount_id(descriptor), info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)


def private_control(descriptor):
    info = os.fstat(descriptor)
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600)


def journal_record(control):
    fd = os.open("exchange.json", FILE, dir_fd=control)
    with os.fdopen(fd, "rb") as stream:
        require(private_control(fd), "Alternate exchange journal is not private")
        first = os.fstat(fd)
        raw = stream.read(65537)
        latest = os.stat("exchange.json", dir_fd=control, follow_symlinks=False)
        require(len(raw) <= 65536 and os.path.samestat(first, latest)
                and first.st_ctime_ns == latest.st_ctime_ns, "Alternate exchange journal changed")
        return json.loads(raw)


def verify_exchange(fence):
    """Check the exact complete closed exchange. Never create controls or move an endpoint."""
    require(fence.launch_uid == os.geteuid() and fence.launch_uid > 0, "Wrong alternate writer account")
    ns = Path("/proc/self/ns/mnt").stat()
    require((ns.st_dev, ns.st_ino) == fence.namespace, "Wrong alternate writer mount namespace")
    require(fence.parent.is_absolute() and fence.parent.resolve(strict=True) == fence.parent
            and fence.control.is_absolute() and fence.control.resolve(strict=True) == fence.control,
            "Exchange paths are not canonical")
    names = tuple(name for pair in fence.pairs for name in pair)
    require(fence.pairs and len(set(names)) == len(names)
            and all(name not in {"", ".", ".."} and Path(name).name == name for name in names)
            and all(right.startswith(".exchange-park-") for _, right in fence.pairs),
            "Alternate exchange route names are not distinct canonical siblings")
    routes = fence.active_roots() | fence.parked_roots()
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        mounted = Path(mount_path(line.split()[4]))
        require(not any(mounted.is_relative_to(route) for route in routes),
                "Nested mount overlaps an alternate checkout fence")
    parent = os.open(fence.parent, DIR)
    try:
        require(directory_identity(parent) == fence.parent_identity, "Alternate checkout parent changed")
        control = os.open(fence.control, DIR)
        try:
            require(directory_identity(control) == fence.control_identity
                    and fence.control_identity[3] == fence.launch_uid and fence.control_identity[5] == 0o700,
                    "Alternate exchange control directory changed")
            lock = os.open("exchange.lock", FILE, dir_fd=control)
            try:
                require(private_control(lock) and directory_identity(lock) == fence.lock_identity,
                        "Alternate exchange controller lock changed")
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                journal = journal_record(control)
                intent = journal["intent"]
                raw_intent = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
                require(journal["phase"] == "closed" and journal["completed"] == len(fence.pairs)
                        and journal["terminal_proof_sha256"] is None
                        and intent["schema"] == fence.intent_schema and intent["generation"] == fence.generation
                        and journal["intent_sha256"] == fence.intent_sha256 == sha256(raw_intent).hexdigest()
                        and tuple(tuple(pair["names"]) for pair in intent["pairs"]) == fence.pairs,
                        "Alternate exchange is not the approved closed generation")
                for pair in intent["pairs"]:
                    for name, kind in zip(pair["names"], ("sentinel", "original"), strict=True):
                        endpoint = os.open(name, DIR, dir_fd=parent)
                        try:
                            actual = directory_identity(endpoint)
                            require(actual == tuple(pair[kind]) and actual[0] == fence.parent_identity[0]
                                    and actual[2] == fence.parent_identity[2] and actual[3] == fence.launch_uid,
                                    "Alternate exchange endpoint does not match its approved identity")
                            if kind == "sentinel":
                                require(actual[5] == 0o500 and not os.listdir(endpoint),
                                        "Closed alternate checkout is not an empty sentinel")
                        finally:
                            os.close(endpoint)
                require(journal_record(control) == journal, "Alternate exchange changed during verification")
            finally:
                os.close(lock)
        finally:
            os.close(control)
    finally:
        os.close(parent)

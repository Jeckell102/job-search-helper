"""Read-only administrator evidence for the two approved system session roles."""
import argparse
from hashlib import sha256
import json
import os
import pwd
import re
import secrets
import socket
import struct
from pathlib import Path
import stat
import time


SCHEMA = "sprint-4-ancillary-process-witness-v1"
ROLES = {"ssh-agent": Path("/usr/bin/ssh-agent"), "(sd-pam)": Path("/usr/lib/systemd/systemd")}
LIMIT = 16384
SOCKET_TIMEOUT = 1.0
CREDENTIALS = struct.Struct('3i')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def file_sha(data):
    return sha256(data).hexdigest()


def process_identity(proc):
    parts = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    require(len(parts) > 19 and parts[0] not in ("Z", "X"), "System process is unavailable")
    return {
        "pid": int(proc.name), "uid": proc.stat().st_uid, "started": int(parts[19]),
        "comm": (proc / "comm").read_text().strip(),
        "cmdline_sha256": file_sha((proc / "cmdline").read_bytes()),
        "cgroup_sha256": file_sha((proc / "cgroup").read_bytes()),
    }


def scope(proc_root, launch_uid, maintenance_id, routes):
    return {
        "boot": (proc_root / "sys/kernel/random/boot_id").read_text().strip(),
        "launch_uid": launch_uid, "maintenance_id": maintenance_id,
        "routes": sorted(map(str, routes)),
    }


def mentions_route(value, routes):
    return any(str(route) in value for route in routes)


def listening_inodes(proc_root, port):
    inodes = set()
    for protocol in ("tcp", "tcp6"):
        for line in (proc_root / "net" / protocol).read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:
                require(protocol == "tcp" and fields[1].split(":")[0] == "0100007F",
                        "Wrapper listener is not confined to IPv4 loopback")
                inodes.add(fields[9])
    return inodes


def listener_request(value, expected_port):
    require(type(value) is dict and set(value) == {"port", "inodes"}
            and type(value["port"]) is int and value["port"] == expected_port
            and 1 <= expected_port <= 65535, "Unapproved listener observation")
    inodes = value["inodes"]
    require(type(inodes) is list and 1 <= len(inodes) <= 32
            and all(type(inode) is str and re.fullmatch(r"[1-9][0-9]{0,19}", inode) for inode in inodes)
            and inodes == sorted(set(inodes)), "Invalid listener identity")
    return expected_port, set(inodes)


def inspect_descriptors(proc, listener):
    if listener is not None:
        port, inodes = listener
        require(listening_inodes(proc.parent, port) == inodes, "Wrapper listener identity changed")
    references = [os.readlink(descriptor) for descriptor in (proc / "fd").iterdir()]
    if listener is not None:
        require(not (set(references) & {f"socket:[{inode}]" for inode in inodes}),
                "System helper shares the wrapper listener")
        require(listening_inodes(proc.parent, port) == inodes, "Wrapper listener identity changed")
    return references


def capture(launch_uid, routes, pid, *, listener=None):
    """Run in an administrator terminal. Output fingerprints, never raw process arguments."""
    require(os.geteuid() == 0, "Administrator process inspection required")
    proc_root = Path("/proc")
    require((proc_root / "1/comm").read_text().strip() == "systemd", "Full system process view required")
    proc = proc_root / str(pid)
    identity = process_identity(proc)
    executable = ROLES.get(identity["comm"])
    exe = Path(os.readlink(proc / "exe"))
    require(executable is not None and identity["uid"] == launch_uid
            and executable.resolve(strict=True) == exe, "Process is outside the approved system helper roles")
    info = exe.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
            and os.path.samestat(info, (proc / "exe").stat()),
            "The live executable differs from the administrator-managed program")
    references = [str(exe), os.readlink(proc / "cwd"), os.readlink(proc / "root")]
    args = (proc / "cmdline").read_bytes()
    require(file_sha(args) == identity["cmdline_sha256"], "System helper command changed")
    references.extend(os.fsdecode(arg) for arg in args.split(b"\0") if arg)
    references.extend(inspect_descriptors(proc, listener))
    require(not any(mentions_route(reference, routes) for reference in references),
            "Selected system helper still references a checkout")
    require(process_identity(proc) == identity
            and os.path.samestat(info, exe.stat()) and os.path.samestat(info, (proc / "exe").stat()),
            "System helper changed during administrator observation")
    return identity


def trusted_directory(path):
    require(path.is_absolute() and path.is_relative_to("/run") and path.resolve(strict=True) == path,
            "Use a physical administrator directory under /run")
    for parent in (path, *path.parents):
        info = parent.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "Administrator observer directory is writable by other users")


def peer_uid(stream):
    return CREDENTIALS.unpack(stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, CREDENTIALS.size))[1]


def receive(stream, deadline):
    data = bytearray()
    while len(data) <= LIMIT:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Administrator observation exceeded its deadline")
        stream.settimeout(min(remaining, SOCKET_TIMEOUT))
        chunk = stream.recv(LIMIT + 1 - len(data))
        if not chunk:
            break
        data.extend(chunk)
    require(0 < len(data) <= LIMIT, "Administrator observer message is unavailable")
    message = json.loads(data)
    require(isinstance(message, dict) and encoded(message) == data, "Administrator observer message is invalid")
    require(time.monotonic() < deadline, "Administrator observation exceeded its deadline")
    return message


def request_privileged(path, request):
    trusted_directory(path.parent)
    info = path.lstat()
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o002,
            "Administrator observer socket is untrusted")
    with socket.socket(socket.AF_UNIX) as client:
        deadline = time.monotonic() + SOCKET_TIMEOUT
        client.settimeout(SOCKET_TIMEOUT)
        client.connect(str(path))
        require(peer_uid(client) == 0 and os.path.samestat(info, path.lstat()),
                "Administrator observer peer changed")
        client.sendall(encoded(request))
        client.shutdown(socket.SHUT_WR)
        return receive(client, deadline)


def verify_ancillary_process(path, proc, launch_uid, maintenance_id, routes, *, listener=None):
    """Request a new current observation from the administrator for this checkpoint."""
    request = {"schema": SCHEMA, "scope": scope(proc.parent, launch_uid, maintenance_id, routes),
               "pid": int(proc.name), "challenge": secrets.token_hex(16)}
    if listener is not None:
        port, inodes = listener
        request["listener"] = {"port": port, "inodes": sorted(inodes)}
    try:
        response = request_privileged(path, request)
    except (OSError, ValueError) as exc:
        raise ValueError("Administrator process observation is unavailable") from exc
    observed = process_identity(proc)
    require(observed["uid"] == launch_uid and observed["comm"] in ROLES
            and response == {"request": request, "process": observed},
            "Administrator evidence does not match the current system helper and challenge")
    return True


def serve(path, launch_uid, maintenance_id, routes, pids, duration, *, listener_port=None):
    """Temporary host-terminal observer. It listens only on a private local Unix socket."""
    require(os.geteuid() == 0, "Administrator process inspection required")
    require((Path("/proc/1/comm").read_text().strip() == "systemd")
            and launch_uid > 0 and pids and len(set(pids)) == len(pids) <= len(ROLES)
            and all(pid > 1 for pid in pids) and routes and len(set(routes)) == len(routes)
            and 1 <= duration <= 3600, "Select the exact helpers, routes and bounded observation window")
    require(all(route.is_absolute() and str(route) != "/" and ".." not in route.parts for route in routes),
            "Use the exact physical maintenance route spellings")
    require(listener_port is None or 1 <= listener_port <= 65535, "Invalid approved listener port")
    trusted_directory(path.parent)
    require(path.is_absolute() and not os.path.lexists(path), "Observer socket path already exists")
    expected = scope(Path("/proc"), launch_uid, maintenance_id, routes)
    deadline = time.monotonic() + duration
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        identity = path.lstat()
        try:
            os.chown(path, 0, pwd.getpwuid(launch_uid).pw_gid)
            os.chmod(path, 0o660)
            server.listen(len(pids))
            print("Administrator process observer ready.", flush=True)
            while (remaining := deadline - time.monotonic()) > 0:
                server.settimeout(min(SOCKET_TIMEOUT, remaining))
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    try:
                        if peer_uid(connection) != launch_uid:
                            continue
                        request_deadline = min(deadline, time.monotonic() + SOCKET_TIMEOUT)
                        request = receive(connection, request_deadline)
                        fields = set(request)
                        base_fields = {"schema", "scope", "pid", "challenge"}
                        require(fields in (base_fields, base_fields | {"listener"})
                                and request["schema"] == SCHEMA and request["scope"] == expected
                                and type(request["pid"]) is int and request["pid"] in pids
                                and isinstance(request["challenge"], str)
                                and re.fullmatch("[0-9a-f]{32}", request["challenge"]),
                                "Unapproved administrator observation")
                        require(time.monotonic() < request_deadline, "Administrator window ended")
                        listener = listener_request(request["listener"], listener_port) if "listener" in request else None
                        result = capture(launch_uid, routes, request["pid"], listener=listener)
                        remaining = request_deadline - time.monotonic()
                        require(remaining > 0, "Administrator window ended")
                        connection.settimeout(remaining)
                        connection.sendall(encoded({"request": request, "process": result}))
                    except (OSError, ValueError):
                        # Keep the socket available for subsequent approved checkpoints.
                        continue
        finally:
            if os.path.lexists(path) and os.path.samestat(identity, path.lstat()):
                path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--launch-uid", type=int, required=True)
    parser.add_argument("--maintenance-id", required=True)
    parser.add_argument("--route", type=Path, action="append", required=True)
    parser.add_argument("--pid", type=int, action="append", required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--listener-port", type=int)
    args = parser.parse_args()
    try:
        serve(args.socket, args.launch_uid, args.maintenance_id, args.route, args.pid, args.seconds,
              listener_port=args.listener_port)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Administrator check held: {exc}\n")


if __name__ == "__main__":
    main()

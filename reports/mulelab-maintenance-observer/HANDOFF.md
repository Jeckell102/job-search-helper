# One-time MuleLab maintenance observer setup

The Codex tool runs with `NoNewPrivs=1`, which means a passwordless sudo
rule would still fail here. The reusable path is a systemd Unix socket.
After one administrator installation, a fresh verifier request starts
a small system service and returns the existing read-only process
witness. The service exits after answering. The socket persists across
reboots and has no command execution or arbitrary file-read interface.

The socket is `/run/jsh-maintenance-observer/observer.sock`. Only the
MuleLab chris peer is admitted. The fixed project and checkout routes,
two approved helper executable roles, known session cgroups and
loopback wrapper port constrain the service. The existing witness
authenticates the privileged peer and verifies fresh challenge, boot,
window identity and observation against the selected live process.
Native release locks, exact approval and service restoration checks
remain as reviewed. New native windows must explicitly select this
permanent socket before they are frozen. An existing native window
with a per-window socket uses its existing observer if already active.

The source and units are staged here. Nine protocol tests passed,
including real Unix-socket exchange and refusal of an unauthorized
peer. One installer custody test covered a regular input and rejected a
FIFO, symlink and aliased staging directory. The unit parser verified both unit files. Runtime verification
with systemd root remains open until the one-time admin install.
No system files, sudoers, release, or services changed during staging.

After the current release window is safely restored, run the single
command in `INSTALL_COMMAND.txt` in a regular MuleLab terminal. It
verifies the staged installer bytes before calling sudo. The installer
then verifies the fixed archive, writes four pinned root-owned files,
and enables the socket. The command may ask for the admin password
once. Run `verify_live.py` afterward from the ordinary Codex tools with
the exact helper PIDs from the live host policy. Once it passes, new
reviewed native release plans can use the standing socket without a
manual terminal command per release.

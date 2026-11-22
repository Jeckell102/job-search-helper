# MuleLab permanent read-only maintenance observer

The owner requested an end to recurring administrator terminal prompts
for the maintenance observer. The Codex process runs with NoNewPrivs,
so a sudoers exception would not support the task. The selected setup
uses a root-owned systemd socket at
`/run/jsh-maintenance-observer/observer.sock`. It accepts only the
authorized local user and starts one bounded read-only witness service
per challenge. The protocol is limited to the approved helper roles,
fixed project routes and loopback wrapper listener. The existing
maintenance locks, release decision and restoration checks still apply.

Independent review accepted the corrected one-time installer after its
input was constrained to a private directory and a checked regular
single-link archive. Ten focused disposable tests passed. The owner
installed the socket once. From the ordinary Codex session, the existing
challenged verification succeeded for both live helper processes and the
wrapper listener. systemd reports the socket enabled and active. No
sudoers rule, password storage, Jetson change, or scraper restart was
needed for this installation.

The installed root-owned source files are
`/usr/local/libexec/jsh-maintenance-observer/observe_once.py` and
`/usr/local/libexec/jsh-maintenance-observer/ancillary_process_witness.py`.
The system unit files are
`/etc/systemd/system/jsh-maintenance-observer.socket` and
`/etc/systemd/system/jsh-maintenance-observer@.service`.

For a future window, set its measured verifier to the permanent socket
and use that window's own checked maintenance identity. Authenticate a
fresh challenge to both helpers and the listener under the then-current
host policy. Do not rewrite a completed maintenance journal to change
its observer path. The installed socket is enabled at boot. Reboot
behavior was not exercised. Scoped uninstallation is the administrator
disabling and stopping this socket, removing the two exact unit and two
source files, and reloading the system manager.

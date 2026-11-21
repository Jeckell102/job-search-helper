# Live one-request enrollment readback failure, November 21 at 16:32 Eastern

The verified builder was installed and running on PID 652287. The
accepted one-request enrollment owned only `operator-amphenol-20261121-05`.
Read-only native preflight passed. The first arm saved the exact private
owner and set its one service-manager variable. Its display readback then
raised `Scoped service-manager change did not settle`. The wrapper kept
the same PID and did not load the scope. No scrape or inference had begun.

Live `systemctl --user show-environment` rendered the canonical JSON
value as `$'{"…"}'`. The former `shlex` path kept a literal `$`, so it
could not match the exact saved owner. The independent reviewer reproduced
the failure with the original helper `2a00894c…` without touching native
state. Root verified the live variable matched the exact owner record
in this display format before retrying.

The correction recognizes only this literal quoting around an unescaped
value; unfamiliar escapes still stop inspection. Existing ownership,
locks, service generation and retry checks remain in place. Independent
QA passed five manager/transition cases. The corrected native arm reused
the exact owner and manager write and restarted the wrapper once into
the one-request scope. [Independent QA](S5_AMPHENOL_SYSTEMD_ENROLLMENT_QA_20261121.md).

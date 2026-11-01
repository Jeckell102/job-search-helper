"""Local-only systemd startup condition. Never contacts Google."""
from datetime import datetime, timezone
import sys


def allowed(deadline, now=None):
    cutoff = datetime.fromisoformat(deadline)
    if cutoff.tzinfo is None:
        raise ValueError('Expiration must include a timezone.')
    return (now or datetime.now(timezone.utc)) < cutoff


if __name__ == '__main__':
    try:
        permitted = len(sys.argv) == 2 and allowed(sys.argv[1])
    except (ValueError, TypeError):
        permitted = False
    if not permitted:
        print('Automatic Google Sheets sync has expired. Local job data is unchanged.', flush=True)
    raise SystemExit(0 if permitted else 1)

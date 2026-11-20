"""Reuse interrupted detail work only against a fresh, matching listing.

A completed checkpoint is evidence of a previous scan, not a permanent cache.
Adapters retain ownership of source validation and atomic checkpoint writes.
"""


from .cooperative_fetch import current_scan_scope


def checkpoint_payload(value):
    """Stamp durable work with the active scan; explicit standalone calls use ''."""
    return dict(value, scan_scope=current_scan_scope())


def reusable_details(saved, entries, *, entry_id, job_id):
    """Return matching unfinished details; malformed legacy caches fail closed."""
    if not isinstance(saved, dict) or saved.get('phase') not in {'listing', 'details', 'partial', 'blocked'}:
        return {}
    scope = current_scan_scope()
    if scope and saved.get('scan_scope') != scope:
        return {}
    previous = saved.get('entries')
    jobs = saved.get('jobs')
    if not isinstance(previous, list) or not isinstance(jobs, list):
        return {}
    from .ats import FetchError
    try:
        before = {str(entry_id(entry)): entry for entry in previous}
        current = {str(entry_id(entry)): entry for entry in entries}
        if len(before) != len(previous) or len(current) != len(entries):
            return {}
        matched = {key for key, entry in current.items() if before.get(key) == entry}
        result = {}
        for job in jobs:
            if not isinstance(job, dict) or not job.get('description') or job.get('is_closed'):
                continue
            key = str(job_id(job))
            if key in matched:
                if key in result:
                    return {}
                result[key] = job
        return result
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, FetchError):
        return {}

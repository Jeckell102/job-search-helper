"""The small, human-facing Sheets view of the full local record schema."""
from .repository import SCHEMAS, RepositoryError

COMPACT_PROFILE = 'compact-v1'
LOCAL_ONLY_FIELDS = {
    'Companies': {'Scan State', 'Active Cycle ID', 'Last Successful Scan', 'Claimed By',
                  'Claim Expires At', 'Claim Token', 'Coverage Status',
                  'Last Inventory Count', 'Record Updated'},
    'Job History': {'Description Hash', 'Current Snapshot', 'Reconsideration Count',
                    'Reconsideration Status', 'Consecutive Missing Scans',
                    'Last Seen In Inventory', 'Prior Job Key', 'Recheck Limit',
                    'Record Updated', 'Source Last Modified', 'Review Started At',
                    'Decision', 'Source Hash', 'Job Description'},
}
COMPACT_SCHEMAS = {
    tab: [h for h in SCHEMAS[tab] if h not in LOCAL_ONLY_FIELDS.get(tab, set())]
    for tab in ('Companies', 'Opportunities', 'Job History')
}
COMPACT_SCHEMAS['Opportunities'].append('Opportunity ID')
COMPACT_PULL_FIELDS = {
    'Companies': None,
    'Opportunities': None,
    # Review processing occurs locally. Only deliberate human inputs flow back.
    'Job History': ['Job Key', 'Added to Opportunities?', 'Review Notes'],
}

def profile_schemas(name):
    if not name:
        return None
    if name != COMPACT_PROFILE:
        raise RepositoryError(f'Unknown Sheets publication profile: {name!r}')
    return COMPACT_SCHEMAS

def prune_local_only_delivery(local):
    """Remove obsolete delivery flags, never records or unsent visible fields."""
    schemas = profile_schemas(local.get_meta('sheets_profile'))
    if schemas is None:
        return 0
    count = 0
    with local.transaction():
        for tab, headers in local.schemas.items():
            excluded = set(headers) - set(schemas.get(tab, []))
            if excluded:
                placeholders = ','.join('?' for _ in excluded)
                count += local.db.execute(
                    f'DELETE FROM dirty WHERE tab=? AND header IN ({placeholders})',
                    (tab, *sorted(excluded))).rowcount
        if count:
            local.event('local_only_delivery_pruned', detail={'fields': count})
    return count

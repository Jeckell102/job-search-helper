from contextlib import closing


def require_no_active_application_work(project):
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.retained_cycle_retirement_control import verified_retired_cycle_ids
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
    from job_search_helper.runner import FINISHED, active_inbox_cycles
    from job_search_helper.scan_request import superseded_cycle_ids

    root = project / '.state'
    assert_normal_lifecycle_not_held(root, root / 'jobs.sqlite3')
    destination = InventoryInbox.destination_id(root / 'inventories.sqlite3')
    with (closing(State(root / 'state.db', readonly=True)) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', destination, readonly=True)) as inbox):
        cycles = state.cycles()
        retired = verified_retired_cycle_ids(state)
        excluded = retired | superseded_cycle_ids(cycles)
        if (any(cycle['id'] not in excluded and cycle['status'] not in FINISHED for cycle in cycles)
                or active_inbox_cycles(inbox, state)):
            raise ValueError('An unfinished scrape still owns the running application.')

from unittest.mock import patch

import pytest

from job_search_helper.control_before_prefix_runner import (
    preview_control_before_prefix_source_transition,
)


@pytest.mark.parametrize("journal_suffix", ["-wal", "-journal"])
def test_source_transition_refuses_uncheckpointed_inputs_before_opening(
        tmp_path, journal_suffix):
    inventories = tmp_path / "inventories.sqlite3"
    jobs = tmp_path / "jobs.sqlite3"
    inventories.touch()
    jobs.touch()
    jobs.with_name(jobs.name + journal_suffix).write_bytes(b"pending changes")
    with patch("sqlite3.connect") as connect:
        with pytest.raises(ValueError, match="requires checkpointed databases"):
            preview_control_before_prefix_source_transition(
                inventories, jobs, "CYC-test", "COMP-test")
        connect.assert_not_called()

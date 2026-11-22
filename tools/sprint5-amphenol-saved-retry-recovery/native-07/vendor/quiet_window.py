"""Bound one qualified operator release to the existing systemd fence."""

from contextlib import contextmanager
from pathlib import Path
import re
import stat

from amphenol_operator_one_shot import run_operator_release
from amphenol_operator_retained_release import _physical_directory
from controller import Systemd, present, read_object, write
from installer import encode
from job_search_helper.cli import PROJECT_ROOT, job_database_path, load_environment, state_path, storage_backend
from job_search_helper.integration_release import assert_release_settled


class OperatorQuietWindow:
    """Use one freshly admitted private window and retain its restoration proof."""

    def __init__(self, units, journal, release_id, application_state, *, admission,
                 verify_exclusion, verify_restored):
        self.units = units
        self.journal = Path(journal)
        self.release_id = release_id
        self.application_state = Path(application_state)
        self.admission = admission
        self.verify_exclusion = verify_exclusion
        self.verify_restored = verify_restored

    def _binding(self):
        directory = _physical_directory(self.journal.parent)
        state = _physical_directory(self.application_state)
        load_environment(PROJECT_ROOT / '.env')
        if (type(self.units) is not Systemd or directory is None or state is None
                or storage_backend() != 'sqlite' or state_path() != state / 'state.db'
                or job_database_path() != state / 'jobs.sqlite3'
                or stat.S_IMODE(directory.stat().st_mode) != 0o700
                or self.units.sentinel != directory / 'operator-hold-active'
                or self.journal != directory / 'operator-quiet-window.json'
                or not isinstance(self.release_id, str) or not re.fullmatch(r'REL-[0-9a-f]{24}', self.release_id)
                or not all(callable(item) for item in (
                    self.admission, self.verify_exclusion, self.verify_restored,
                ))):
            raise ValueError('The fresh operator maintenance window is unavailable.')
        return {
            'schema': 'amphenol-operator-quiet-window-v1',
            'release_id': self.release_id,
            'state_directory': str(state),
            'unit_directory': str(self.units.directory),
            'systemctl': str(self.units.exe),
            'sentinel': str(self.units.sentinel),
        }

    def _save(self, record, phase):
        new = record | {'phase': phase}
        write(self.journal, encode(new), replace=phase != 'CLOSING')

    def _restore(self, record):
        # Startup must keep a nonterminal application release fenced for its
        # already supported recovery. Never undo a write on behalf of the worker.
        assert_release_settled(self.application_state)
        self._save(record, 'RESTORING')
        try:
            self.units.restore(record['prior'])
            if self.verify_restored(record['prior']) is not True:
                raise ValueError('The restored operator host could not be verified.')
        except BaseException:
            # The restore may have started the process before a later proof
            # failed. Reestablish the exact fence before releasing admission.
            self.units.close(record['prior'])
            raise
        self._save(record, 'RESTORED')

    @contextmanager
    def hold(self):
        binding = self._binding()
        # The enrolled caller holds a fresh deployment lease and prevents
        # alternate checkout writers without taking the worker's app locks.
        with self.admission():
            if present(self.journal):
                raise ValueError('This operator maintenance window already has a journal.')
            assert_release_settled(self.application_state)
            prior = self.units.snapshot()
            record = {'binding': binding, 'prior': prior}
            self._save(record, 'CLOSING')
            try:
                self.units.close(prior)
                if self.verify_exclusion() is not True:
                    raise ValueError('Operator writer exclusion could not be verified.')
                self.units.verify(prior)
                self._save(record, 'HELD')
                yield
            finally:
                self._restore(record)

    def restore(self):
        """Restore the exact retained unit snapshot after a process interruption."""
        binding = self._binding()
        with self.admission():
            saved = read_object(self.journal)
            if (set(saved) != {'binding', 'prior', 'phase'} or saved['binding'] != binding
                    or saved['phase'] not in {'CLOSING', 'HELD', 'RESTORING', 'RESTORED'}):
                raise ValueError('The retained operator maintenance journal does not match its owner.')
            if saved['phase'] == 'RESTORED':
                self.units.check_status(saved['prior'], held=False, restored=True)
                if self.verify_restored(saved['prior']) is not True:
                    raise ValueError('The restored operator host could not be verified.')
            else:
                self._restore(saved)
            return {'state': 'OPERATOR_MAINTENANCE_RESTORED', 'release_id': self.release_id}

    def run(self, *, approval, original_outcome, request_sha256, historical_task_id, execute=False):
        if execute is True and getattr(approval, 'release_id', None) != self.release_id:
            return {'state': 'HELD_OPERATOR_MAINTENANCE_RELEASE'}
        return run_operator_release(
            approval=approval, original_outcome=original_outcome, request_sha256=request_sha256,
            historical_task_id=historical_task_id, maintenance_scope=self.hold, execute=execute,
        )

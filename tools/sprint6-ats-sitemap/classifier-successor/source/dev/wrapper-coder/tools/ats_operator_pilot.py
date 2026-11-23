"""Default-off, receipt-owned ATS Corporation parser pilot."""

from dataclasses import dataclass, field
import json
import os
import re

from ats_parser_assignment import EXAMPLE_TEST, TARGET, TEST, WORK_ORDER, is_assignment
from embraer_operator_pilot import EmbraerOperatorEnrollment, EmbraerSuccessorAuthorization
from job_search_helper.operator_partial_scope import ATS_CORPORATION


ENV = 'WRAPPER_ATS_OPERATOR_PILOT_ENROLLMENT'
BASE_SOURCE_FILES = frozenset({
    'src/job_search_helper/ats.py',
    'src/job_search_helper/successfactors.py',
    'src/job_search_helper/successfactors_sitemap.py',
    'src/job_search_helper/ats_sitemap_parser.py',
})
SOURCE_FILES = BASE_SOURCE_FILES | {TARGET}


@dataclass(frozen=True)
class ATSOperatorEnrollment(EmbraerOperatorEnrollment):
    input_pins: dict = field(default_factory=dict)
    scope = ATS_CORPORATION
    target = TARGET
    profile_id = WORK_ORDER
    test_paths = (TEST, EXAMPLE_TEST, 'tests/test_successfactors.py')
    max_sessions = 1
    repair_instructions = ' Implement only the assigned ATS posting-path function. MuleLab owns the XML and shared dispatcher.'

    @property
    def source_files(self):
        return dict(self.input_pins)

    def _read_settlement_source(self, repository, record):
        from job_search_helper.operator_embraer_settlement import read_operator_partial_source

        return read_operator_partial_source(repository, record, self.request_sha256, scope=self.scope)

    def approved_edit_owner(self, coordinator, state):
        if not is_assignment(state) or state['repair_provenance']['source_revision'] != self.source_revision:
            return None
        try:
            with self.owner_scope() as (project, jobs, destination):
                source = self._source(jobs, destination)
                if source is None or not source['acknowledged'] or not self._sources_match(project):
                    return None
                pair = self.resolve_owned_pair(coordinator.store, source)
                if pair is None or pair[1] is None or pair[1]['id'] != state['id']:
                    return None
                proposal = self._proposal(pair[0], source['company'])
                if proposal is not None and self._task_matches(*pair, proposal):
                    return source['record']['outcome_id']
                return None
        except (KeyError, OSError, TypeError, ValueError, RuntimeError):
            return None

    @classmethod
    def from_process_environment(cls, environ=None):
        value = (os.environ if environ is None else environ).get(ENV)
        if value is None:
            return None
        keys = {'request_id', 'source_revision', 'request_sha256', 'baseline_sha256', 'source_files'}
        try:
            pairs = json.loads(value, object_pairs_hook=tuple) if isinstance(value, str) and len(value) <= 2000 else None
            if not isinstance(pairs, tuple) or len(pairs) != len(dict(pairs)):
                raise ValueError('Invalid ATS enrollment.')
            data = dict(pairs)
            successor = None
            if 'successor' in data:
                pending = data.pop('successor')
                if not isinstance(pending, tuple) or len(pending) != len(dict(pending)):
                    raise ValueError('Invalid ATS successor authorization.')
                successor = EmbraerSuccessorAuthorization(**dict(pending))
                if not successor.valid() or successor.outcome_id == successor.predecessor_outcome_id:
                    raise ValueError('Invalid ATS successor authorization.')
            pin_pairs = data.get('source_files')
            if not isinstance(pin_pairs, tuple) or len(pin_pairs) != len(dict(pin_pairs)):
                raise ValueError('Invalid ATS source pins.')
            pins = dict(pin_pairs)
            hashes = [data[key] for key in ('source_revision', 'request_sha256', 'baseline_sha256')] + list(pins.values())
            expected_paths = SOURCE_FILES if successor is not None else BASE_SOURCE_FILES
            if (set(data) != keys or set(pins) != expected_paths
                    or not isinstance(data['request_id'], str)
                    or re.fullmatch(r'operator-ats-[A-Za-z0-9][A-Za-z0-9._-]{0,105}', data['request_id']) is None
                    or not all(isinstance(item, str) and re.fullmatch(r'[0-9a-f]{64}', item) for item in hashes)):
                raise ValueError('Invalid ATS enrollment.')
            return cls(
                data['request_id'], data['source_revision'], data['request_sha256'],
                pins['src/job_search_helper/successfactors.py'], pins['src/job_search_helper/ats.py'],
                data['baseline_sha256'], successor=successor, input_pins=pins,
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError('Invalid exact ATS Corporation operator pilot enrollment.') from None

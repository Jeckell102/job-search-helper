"""The explicit company-only operator partial paths."""

from dataclasses import dataclass
import re

from .ats import (
    ACQUIRETM_PAGINATION_CODE, ATS_CORPORATION_SOURCE, ATS_LISTING_RANGE_CODE,
    BREEZY_EMBRAER_HEADING_CODE, CROWN_LISTING_RANGE_CODE,
)
from .successfactors import CROWN_SOURCE


@dataclass(frozen=True)
class OperatorPartialScope:
    slug: str
    company_id: str
    company_name: str
    provider: str
    careers_url: str
    board_url: str
    failure_category: str
    failure_code: str

    @property
    def settlement_schema(self):
        return f'operator-{self.slug}-partial-settlement-v1'

    @property
    def settlement_table(self):
        return f'operator_{self.slug}_settlements'

    @property
    def observation_field(self):
        return f'operator_{self.slug}_observation_sha256'


_AMPHENOL_URL = 'https://amphenol-aerospace.acquiretm.com/home.aspx'
AMPHENOL = OperatorPartialScope(
    'amphenol', 'COMP-0490', 'Amphenol Aerospace', 'AcquireTM', _AMPHENOL_URL, _AMPHENOL_URL,
    'pagination_regression', ACQUIRETM_PAGINATION_CODE,
)
EMBRAER = OperatorPartialScope(
    'embraer', 'COMP-0634', 'Embraer', 'Breezy HR', 'https://www.embraer.com/careers/',
    'https://embraer.breezy.hr/', 'full_description_regression', BREEZY_EMBRAER_HEADING_CODE,
)

CROWN = OperatorPartialScope(
    'crown', 'COMP-0588', 'Crown Equipment', 'SuccessFactors', 'https://us-careers.crown.com/',
    CROWN_SOURCE, 'pagination_regression', CROWN_LISTING_RANGE_CODE,
)

CROWN_REQUEST_PREFIX = 'operator-crown-'
CROWN_REQUEST_ID = re.compile(r'operator-crown-[A-Za-z0-9][A-Za-z0-9._-]{0,105}')


ATS_CORPORATION = OperatorPartialScope(
    'ats', 'COMP-0573', 'ATS Corporation', 'SuccessFactors', 'https://jobs.atsautomation.com/',
    ATS_CORPORATION_SOURCE, 'pagination_regression', ATS_LISTING_RANGE_CODE,
)
ATS_REQUEST_PREFIX = 'operator-ats-'
ATS_REQUEST_ID = re.compile(r'operator-ats-[A-Za-z0-9][A-Za-z0-9._-]{0,105}')


def require_operator_partial_scope(scope):
    if all(scope is not allowed for allowed in (AMPHENOL, EMBRAER, CROWN, ATS_CORPORATION)):
        raise ValueError('Unsupported operator partial scope.')

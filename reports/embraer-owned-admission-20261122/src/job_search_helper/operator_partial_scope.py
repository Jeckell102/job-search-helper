"""The two explicit company-only operator partial paths."""

from dataclasses import dataclass

from .ats import ACQUIRETM_PAGINATION_CODE, BREEZY_EMBRAER_HEADING_CODE


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


def require_operator_partial_scope(scope):
    if scope is not AMPHENOL and scope is not EMBRAER:
        raise ValueError('Unsupported operator partial scope.')

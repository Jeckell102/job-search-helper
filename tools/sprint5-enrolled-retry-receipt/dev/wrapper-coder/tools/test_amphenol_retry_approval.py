import json

import pytest

from amphenol_retry_completion import RetryReleaseApproval
from test_amphenol_host_enrollment import host


def test_retry_approval_requires_original_enrollment(host, tmp_path):
    receipt = {
        'release_id': 'REL-' + '1' * 24, 'directory': str(tmp_path),
        'device': tmp_path.stat().st_dev, 'inode': tmp_path.stat().st_ino,
        'receipt_sha256': '2' * 64,
    }
    approval = json.dumps(receipt)
    event = 'CEV-' + '3' * 32
    origin = json.dumps({
        'company_event_id': event, 'request_id': 'company-event:' + event,
        'source_revision': '4' * 64,
    })
    with pytest.raises(ValueError, match='requires exact recipe enrollment'):
        host.AmphenolRecipeEnrollment.from_process_environment({'WRAPPER_AMPHENOL_RETRY_APPROVAL': approval})

    env = {'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': origin}
    assert host.AmphenolRecipeEnrollment.from_process_environment(env).retry_approval is None
    env['WRAPPER_AMPHENOL_RETRY_APPROVAL'] = approval
    assert host.AmphenolRecipeEnrollment.from_process_environment(env).retry_approval == RetryReleaseApproval(**receipt)
    for revision in ({'receipt_sha256': 'bad'}, {'inode': True}, {'directory': 'relative'}, {'release_id': 'other'}):
        env['WRAPPER_AMPHENOL_RETRY_APPROVAL'] = json.dumps({**receipt, **revision})
        with pytest.raises(ValueError, match='Invalid exact Amphenol'):
            host.AmphenolRecipeEnrollment.from_process_environment(env)

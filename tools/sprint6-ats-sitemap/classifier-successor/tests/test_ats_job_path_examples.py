"""The path examples supplied to the model are also immutable executable checks."""
import json
from pathlib import Path

import pytest

from job_search_helper.ats_job_path import classify_job_path


def test_ats_job_path_examples():
    examples = Path(__file__).parent / 'fixtures/ats_job_path_examples.json'
    assert callable(classify_job_path)
    for case in json.loads(examples.read_text()):
        if 'returns' in case:
            assert classify_job_path(case['path']) == case['returns'], case
        else:
            assert case['raises'] == 'ValueError'
            with pytest.raises(ValueError):
                classify_job_path(case['path'])

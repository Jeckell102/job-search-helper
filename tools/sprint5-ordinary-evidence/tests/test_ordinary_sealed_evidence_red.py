"""Expose the missing normal provider-observation to sealed-evidence handoff."""
from hashlib import sha256
import json
from pathlib import Path
from shutil import copytree
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PIN_FIELDS = ('company_id', 'source_revision', 'capability_id', 'capability_digest',
              'mapping_digest', 'configuration_digest')
OUTCOME = 'QUALIFIED_INTEGRATION_REPAIR'


class MissingSealedEvidence(AssertionError):
    """A successful fixture reached the known-red normal evidence boundary."""


def run_mode(tmp_path, mode):
    installed = tmp_path / f'installed-{mode}'
    copytree(ROOT / 'frozen-source', installed)
    source = installed / 'src/job_search_helper/company_sources.py'
    good = b'https://ats.rippling.com/forterra/jobs'
    stale = b'https://ats.rippling.com/forterra-retired-fixture/jobs'
    raw = source.read_bytes()
    assert raw.count(good) == 1
    source.write_bytes(raw.replace(good, stale))
    manifest_path = installed / 'src/job_search_helper/source_configuration_manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    [mapping] = [entry for entry in manifest['mappings'] if entry['company_id'] == 'COMP-0066']
    assert mapping['configured_url'] == good.decode()
    mapping['configured_url'] = stale.decode()
    mapping['company_sources_sha256'] = sha256(source.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n')
    empty_home = tmp_path / 'empty-home'
    empty_home.mkdir()
    result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tests/ordinary_probe.py'), str(installed), mode],
                            cwd=installed, env={'PATH': '/usr/bin:/bin', 'HOME': str(empty_home), 'TMPDIR': str(tmp_path)},
                            capture_output=True, text=True, timeout=40)
    (tmp_path / 'normal-worker.log').write_text(result.stdout + '\n' + result.stderr)
    assert result.returncode == 0, f'fixture failed before the evidence check:\n{result.stdout}\n{result.stderr}'
    return json.loads((installed / 'probe-evidence.json').read_bytes())


def assert_verified_inputs(evidence):
    assert not evidence['offline']['forbidden_io_attempts']
    assert evidence['provider_requests'] == [evidence['installed_snapshot']['configured_url']]
    assert evidence['runtime_binding']['state'] == 'NO_RELEASE'
    assert evidence['fake_publication']['pending_after'] == 0
    assert evidence['fake_publication']['cycle_id'] == evidence['cycle_id']
    assert evidence['independent_proof']['candidate']['company_id'] == 'COMP-0066'
    assert evidence['independent_proof']['pdw_regression']['company_id'] == 'COMP-0178'
    assert evidence['independent_proof']['candidate']['board'] != evidence['provider_requests'][0]


def test_default_off_normal_scrape_holds_without_a_sealed_repair(tmp_path):
    evidence = run_mode(tmp_path, 'default-off')
    assert_verified_inputs(evidence)
    assert evidence['qualification'] is None
    assert not evidence['group_fields'] and evidence['mapping_fact_count'] == 0
    assert evidence['descriptors_before'] == evidence['descriptors_after']
    assert [record['outcome'] for record in evidence['outcomes']] == ['UNKNOWN_CAPABILITY_HOLD']
    assert [record['action'] for record in evidence['outcomes']] == ['hold_for_engineering']


@pytest.mark.xfail(strict=True, raises=MissingSealedEvidence,
                   reason='normal scrape has no authoritative mapping-fact producer and checkpoint handoff')
def test_reviewed_normal_scrape_should_checkpoint_and_emit_one_sealed_repair(tmp_path):
    evidence = run_mode(tmp_path, 'reviewed')
    assert_verified_inputs(evidence)
    qualified = evidence['qualification']['qualification']
    assert qualified['category'] == 'same_provider_source_mapping'
    assert qualified['evidence_code'] == 'rippling_verified_mapping_divergence'
    assert all(qualified[key] == evidence['installed_snapshot'][key] for key in PIN_FIELDS)
    outcomes = [record['outcome'] for record in evidence['outcomes']]
    if not evidence['group_fields'] and evidence['mapping_fact_count'] == 0 and outcomes == ['UNKNOWN_CAPABILITY_HOLD']:
        raise MissingSealedEvidence(
            'Exact qualification matched and the normal provider observed stale Rippling tenant scope. '
            'Independent employer, candidate and PDW evidence was available. '
            'The normal run emitted UNKNOWN_CAPABILITY_HOLD without a durable mapping fact or sealed cycle group.'
        )
    assert evidence['mapping_fact_count'] == 1
    assert set(evidence['group_fields']) == {
        'source_configuration_mapping_fact', 'source_configuration_defect',
        'source_configuration_qualification_evidence',
    }
    assert outcomes == [OUTCOME]
    record, = evidence['outcomes']
    assert record['repair_category'] == 'same_provider_source_mapping'
    assert record['identity']['source_revision'] == qualified['source_revision']
    for key in ('capability_id', 'capability_digest', 'mapping_digest', 'configuration_digest'):
        assert record[key] == qualified[key]

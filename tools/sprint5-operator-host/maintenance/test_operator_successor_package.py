"""Focused source-only checks for the selected-operator successor schema."""
from hashlib import sha256
import importlib.util
import sys
from pathlib import Path

import pytest

import installer


def _row(index, *, absent=False):
    return {
        "before": None if absent else {"mode": "0644", "sha256": f"{index:064x}"},
        "after": {"mode": "0644", "sha256": f"{index + 100:064x}"},
        "owner": [1000, 1000],
    }


def packet():
    return {
        "schema": installer.OPERATOR_SCHEMA,
        "paths": {path: _row(index, absent="operator_" in path)
                  for index, path in enumerate(sorted(installer.OPERATOR_PATHS), 1)},
    }


def load(tmp_path, value, *, module=installer):
    raw = module.encode(value)
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    return module.load_manifest(path, sha256(raw).hexdigest())


def test_operator_schema_accepts_only_the_exact_nine_paths(tmp_path):
    result = load(tmp_path, packet())
    assert result.schema == installer.OPERATOR_SCHEMA
    assert set(result.paths) == installer.OPERATOR_PATHS
    assert len(result.paths) == 9


@pytest.mark.parametrize("path", sorted(installer.OPERATOR_PATHS))
def test_operator_schema_refuses_each_omission(tmp_path, path):
    value = packet()
    del value["paths"][path]
    with pytest.raises(ValueError, match="exact reviewed source paths"):
        load(tmp_path, value)


@pytest.mark.parametrize("path", [
    "src/job_search_helper/scan_request.py",
    "dev/wrapper-coder/tools/coordinator_receipt_host_bridge.py",
    "dev/wrapper-coder/tools/unreviewed.py",
])
def test_operator_schema_refuses_extra_or_protected_paths(tmp_path, path):
    value = packet()
    value["paths"][path] = _row(99)
    with pytest.raises(ValueError, match="exact reviewed source paths"):
        load(tmp_path, value)


def test_operator_schema_requires_existing_host_and_choice(tmp_path):
    for path in ("dev/wrapper-coder/tools/host_server.py",
                 "dev/wrapper-coder/tools/amphenol_recipe_choice_input.py"):
        value = packet()
        value["paths"][path]["before"] = None
        with pytest.raises(ValueError, match="existing host and choice"):
            load(tmp_path, value)


@pytest.mark.parametrize("path", sorted(installer.OPERATOR_EXISTING_PATHS))
def test_operator_schema_refuses_absent_before_for_existing_endpoint(tmp_path, path):
    value = packet()
    value["paths"][path]["before"] = None
    with pytest.raises(ValueError, match="(before-images for every existing|existing host and choice)"):
        load(tmp_path, value)


@pytest.mark.parametrize("path", sorted(installer.OPERATOR_ADDITIONS))
def test_operator_schema_refuses_before_image_for_new_operator_module(tmp_path, path):
    value = packet()
    value["paths"][path]["before"] = _row(200)["before"]
    with pytest.raises(ValueError, match="absent-before operator additions"):
        load(tmp_path, value)


def test_prior_schema_sets_and_installed_predecessor_guard_are_preserved(tmp_path):
    baseline_path = "/tmp/jsh-retirement-merged-release.RvLEs074/maintenance_policy/installer.py"
    spec = importlib.util.spec_from_file_location("approved_retirement_installer", baseline_path)
    approved = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = approved
    spec.loader.exec_module(approved)
    assert installer.CONSOLIDATED_PATHS == approved.CONSOLIDATED_PATHS
    assert installer.RETIREMENT_PATHS == approved.RETIREMENT_PATHS
    assert installer.CONSOLIDATED_WRAPPER_PATHS == approved.CONSOLIDATED_WRAPPER_PATHS
    source = (Path(__file__).with_name("controller.py")).read_text(encoding="utf-8")
    assert "installer.OPERATOR_SCHEMA" in source
    assert "target == \"ROLLED_BACK\" or installed_predecessor" in source
    value = packet()
    value["schema"] = installer.RETIREMENT_SCHEMA
    with pytest.raises(ValueError, match="exact reviewed source paths"):
        load(tmp_path, value)


def test_legacy_three_wrapper_contract_is_unchanged(tmp_path):
    value = {
        "schema": "sprint-4-source-manifest-v1",
        "paths": {path: _row(index) for index, path in enumerate(sorted(installer.WRAPPER_PATHS), 1)},
    }
    result = load(tmp_path, value)
    assert set(result.paths) == installer.WRAPPER_PATHS

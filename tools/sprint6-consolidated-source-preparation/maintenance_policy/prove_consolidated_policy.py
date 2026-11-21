"""Check the staged exact manifest policy without an installer or service action."""

import argparse
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import controller
import installer


def wrapper_names_as_used(manifest):
    # Exercise the precise constructor assignment without creating a controller
    # or opening its live services, runtime records or application locks.
    tree = ast.parse(Path(controller.__file__).read_text())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Controller')
    constructor = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
    assignment = next(node for node in constructor.body if isinstance(node, ast.Assign)
                      and ast.unparse(node.targets[0]) == 'self.wrapper_names')
    fixture = SimpleNamespace(manifest=manifest)
    namespace = {'self': fixture, 'Path': Path, 'installer': installer}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), '<scoped wrapper paths>', 'exec'), namespace)
    return fixture.wrapper_names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('consolidated_manifest', type=Path)
    parser.add_argument('previous_manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    original_bytes = args.previous_manifest.read_bytes()
    assert sha256(original_bytes).hexdigest() == 'a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163'
    original = installer.load_manifest(args.previous_manifest, sha256(original_bytes).hexdigest())
    original_wrappers = wrapper_names_as_used(original)
    assert len(original.paths) == 47 and original_wrappers == {Path(path).name for path in installer.WRAPPER_PATHS}

    packet = json.loads(args.consolidated_manifest.read_bytes())
    assert packet['schema'] == 'sprint-4-source-manifest-v1'
    packet['schema'] = installer.CONSOLIDATED_SCHEMA
    hold_names = {}

    with TemporaryDirectory(prefix='jsh-maintenance-source-policy.') as directory:
        root = Path(directory)
        current = root / 'manifest.json'

        def load(value, *, pin=None):
            encoded = installer.encode(value)
            current.write_bytes(encoded)
            return installer.load_manifest(current, pin or sha256(encoded).hexdigest())

        def held(name, value, *, pin=None):
            try:
                load(value, pin=pin)
            except ValueError as error:
                hold_names[name] = str(error)
            else:
                raise AssertionError(f'Policy accepted {name}')

        accepted = load(packet)
        assert set(accepted.paths) == installer.CONSOLIDATED_PATHS and len(accepted.paths) == 38
        names = wrapper_names_as_used(accepted)
        assert len(names) == 11
        bridge = 'coordinator_receipt_host_bridge.py'
        assert bridge not in names

        altered = deepcopy(packet)
        del altered['paths'][installer.WRAPPER_HOST]
        held('missing required endpoint', altered)
        altered = deepcopy(packet)
        altered['paths'][str(installer.WRAPPER_PARENT / bridge)] = next(iter(altered['paths'].values()))
        held('retained bridge added to write list', altered)
        altered = deepcopy(packet)
        altered['paths'][installer.WRAPPER_HOST]['before'] = None
        held('missing existing host before-image', altered)
        altered = deepcopy(packet)
        path = 'src/job_search_helper/engine.py'
        altered['paths'][path]['after'] = altered['paths'][path]['before']
        held('unchanged endpoint presented as replacement', altered)
        held('wrong approved manifest digest', packet, pin='f' * 64)
        held('old schema cannot gain the extra source paths', {**packet, 'schema': 'sprint-4-source-manifest-v1'})

        wrappers = root / 'wrapper-tools'
        wrappers.mkdir()
        bridge_file = wrappers / bridge
        bridge_file.write_bytes(b'fixture protected receipt bridge\n')
        host_file = wrappers / 'host_server.py'
        host_file.write_bytes(b'fixture reviewed host\n')
        witness = controller.unscoped(wrappers, names)
        observation = SimpleNamespace(wrapper_tools=wrappers, wrapper_names=names)
        controller.Controller.verify_wrapper_siblings(observation, {'unscoped_wrapper': witness})
        host_file.write_bytes(b'new fixture reviewed host\n')
        controller.Controller.verify_wrapper_siblings(observation, {'unscoped_wrapper': witness})
        bridge_file.write_bytes(b'fixture changed receipt bridge\n')
        try:
            controller.Controller.verify_wrapper_siblings(observation, {'unscoped_wrapper': witness})
        except ValueError as error:
            assert str(error) == 'Non-scope wrapper source changed'
        else:
            raise AssertionError('Controller accepted a changed retained receipt bridge')

    report = {
        'original_approved_manifest_paths': len(original.paths),
        'staged_consolidated_manifest_paths': len(accepted.paths),
        'staged_consolidated_mutable_wrapper_paths': sorted(names),
        'invalid_manifests_refused': hold_names,
        'receipt_bridge_outside_mutation_set': True,
        'controller_rejects_protected_receipt_bridge_drift': True,
        'installer_action_run': False,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

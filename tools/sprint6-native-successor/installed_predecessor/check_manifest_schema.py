"""Read canonical predecessor/successor scopes through the selected parser."""
from hashlib import sha256
import json
from pathlib import Path
import installer

pairs = (
    (Path('/tmp/jsh-consolidated-installer-gate-independent.EMP9isny/accepted_freeform_manifest.json'),
     'a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163', 'sprint-4-source-manifest-v1', 47),
    (Path('/tmp/jsh-maintenance-source-policy-independent.Rrbco88n/transaction-2rkxuecl/exact-38-metadata.json'),
     '8ea29b5ae423c18c0b4b108ea1d337359132433e1ad1b9e0cb39e7179117ea11', installer.CONSOLIDATED_SCHEMA, 38),
)
readback = []
for source, pin, schema, count in pairs:
    assert sha256(source.read_bytes()).hexdigest() == pin
    parsed = installer.load_manifest(source, pin)
    assert parsed.schema == schema and len(parsed.paths) == count and parsed.sha256 == pin
    readback.append({'accepted_schema': parsed.schema, 'path_count': count, 'manifest_sha256': parsed.sha256})
print(json.dumps({'result': 'PASS_EXACT_ARCHIVED_AND_CONSOLIDATED_SCHEMAS', 'readback': readback}, indent=2, sort_keys=True))

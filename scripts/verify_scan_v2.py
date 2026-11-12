"""Offline verification of two generated scans, including a Mermaid subset check.

This is NOT the official Mermaid parser. The validation file keeps that distinction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def mermaid_subset(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    assert lines and lines[0] in {'flowchart LR', 'sequenceDiagram', 'stateDiagram-v2'}, path
    patterns = {
        'flowchart LR': [r'\w+\["[^"\[\]]*"\]', r'\w+ (?:-->|-\.->)\|[^|]+\| \w+'],
        'sequenceDiagram': [r'(?:participant|actor) \w+ as [^\n]+', r'Note over \w+(?:,\w+)?: [^\n]+',
                            r'\w+->>\w+: [^\n]+'],
        'stateDiagram-v2': [r'state "[^"\n]*" as \w+', r'\w+ --> \w+: [^\n]+'],
    }
    for line in lines[1:]:
        assert any(re.fullmatch(pattern, line.strip()) for pattern in patterns[lines[0]]), (path.name, line)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('first', type=Path)
    p.add_argument('second', type=Path)
    p.add_argument('--result', type=Path, required=True)
    a = p.parse_args()
    left, right = hashes(a.first), hashes(a.second)
    assert left == right, 'Non-deterministic artifacts'
    for path in (a.first / 'diagrams').glob('*.mmd'):
        mermaid_subset(path)
    model = json.loads((a.first / 'architecture.json').read_text(encoding='utf-8'))
    inventory = json.loads((a.first / 'inventory.json').read_text(encoding='utf-8'))
    entries = {f['path']: f for f in inventory['files']}
    items = {i['id']: i for i in model['items']}
    assert len(items) == len(model['items'])
    for item in items.values():
        for ev in item['evidence']:
            assert ev['sha256'] == entries[ev['path']]['sha256']
            assert 1 <= ev['start_line'] <= ev['end_line'] <= entries[ev['path']]['lines']
    flows = [i for i in items.values() if i['kind'] == 'flow']
    result = {'artifact_count': len(left), 'identical_bytes': True,
              'source_unchanged_admitted_scope': inventory['unchanged_admitted_scope'],
              'citation_bounds_and_hashes': 'passed', 'mermaid_generated_subset': 'passed',
              'official_mermaid_parser': 'unavailable; not validated', 'linux': 'not tested',
              'inspected_files': len(entries), 'http_unique': sum('target' in f for f in flows),
              'http_unresolved': sum('target' not in f for f in flows),
              'http_with_screen_candidate': sum(bool(f.get('screens')) and 'target' in f for f in flows),
              'async_unique': sum(i['kind'] == 'async_flow' and 'target' in i for i in items.values())}
    a.result.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

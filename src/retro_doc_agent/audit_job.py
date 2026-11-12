"""Prepare a local, evidence-tracked review of the Project Twin V3 audits."""

import argparse
import json
import re
from pathlib import Path

from .pipeline import configuration, excluded, linked, save


def reference_files(root, directory, patterns, exclusions):
    folder = root / directory
    if not folder.is_dir():
        return
    if any(linked(parent) for parent in (folder, *folder.parents) if parent != root and root in parent.parents):
        return
    for path in sorted({path for pattern in patterns for path in folder.glob(pattern)}):
        relative = path.relative_to(root)
        if excluded(relative, exclusions):
            continue
        if any(linked(parent) for parent in (path, *path.parents) if parent != root and root in parent.parents):
            continue
        if path.is_file() and path.stat().st_size <= 1_000_000:
            yield path, relative.as_posix()


def prepare(config, run_id, audit_root):
    cfg, source, output = configuration(config)
    if cfg['network'] != 'disabled' or not isinstance(source, Path):
        raise ValueError('The audit review requires a local source and disabled network.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise ValueError('Invalid run ID.')
    run = output / run_id
    audit_root = audit_root.resolve(strict=True)
    if audit_root == run or run in audit_root.parents or audit_root in run.parents:
        raise ValueError('Audit references must be separate from the run.')
    if linked(run):
        raise ValueError('The run directory must not be a link.')
    manifest_path = run / 'run.json'
    if linked(manifest_path):
        raise ValueError('The inventory manifest must not be a link.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest['source_root'] != str(source) or manifest['config'] != cfg or manifest['stages']['inventory'] != 'completed':
        raise ValueError('The run needs a completed inventory from this configuration.')

    findings = []
    diagrams = []
    for directory, prefix in (
        ('architecture-audit', 'ARCH'),
        ('security-audit/security-audit', 'SEC'),
    ):
        indexes = list(reference_files(audit_root, directory, ('findings/INDEX.md',), cfg['exclude']))
        if len(indexes) != 1:
            raise ValueError(f'Missing or excluded {prefix} index.')
        index, reference = indexes[0]
        rows = []
        for line_number, line in enumerate(index.read_text(encoding='utf-8-sig').splitlines(), 1):
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if not re.fullmatch(fr'{prefix}-\d{{3}}', cells[0]):
                continue
            rows.append({
                'id': cells[0],
                'historical_reference': {'path': reference, 'start_line': line_number, 'end_line': line_number},
                'related_ids': re.findall(r'ARCH-\d{3}', cells[-1]) if prefix == 'SEC' else [],
                'status': 'a_verifier',
                'current_evidence': [],
            })
        if not rows or len({row['id'] for row in rows}) != len(rows):
            raise ValueError(f'Empty or ambiguous {prefix} index.')
        findings.extend(rows)

    for directory in ('architecture-audit', 'security-audit/security-audit', 'solution-analysis'):
        for _, reference in reference_files(audit_root, directory, ('**/*.mmd', '**/*.mermaid'), cfg['exclude']):
            diagrams.append({
                'historical_reference': reference,
                'status': 'a_reconcilier',
                'current_evidence': [],
            })

    destination = run / 'audit-review.json'
    temporary = destination.with_suffix('.json.tmp')
    if destination.exists() or destination.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise ValueError('Audit review already exists for this run.')
    save(destination, {
        'schema_version': 1,
        'source_revision': manifest['source_revision'],
        'status': 'partial',
        'findings': findings,
        'diagrams': diagrams,
        'limitations': [
            'Historical indexes and diagram paths are reference material.',
            'Static inventory alone cannot resolve findings or reconstruct a historical Git diff.',
            'No inspected code, audit commands, tests, or network requests are executed.',
        ],
    })
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config/agent.json'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--audit-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(prepare(args.config, args.run_id, args.audit_root))
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()

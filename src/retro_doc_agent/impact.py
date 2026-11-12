"""Compare completed inventories and prepare review actions without reading source."""

from collections import Counter
import json
from pathlib import PurePosixPath
import re

from .pipeline import configuration, linked, save


def relative_path(value, directory=False):
    if not isinstance(value, str):
        raise ValueError('Invalid inventory path')
    label = value.removesuffix('/') if directory else value
    path = PurePosixPath(label)
    if (not path.parts or path.is_absolute() or path.as_posix() != label
            or '..' in path.parts or any(c in '\\:' or ord(c) < 32 for c in label)):
        raise ValueError('Invalid inventory path')
    return path


def load_inventory(output, run_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', run_id):
        raise ValueError('Invalid run ID')
    folder = output / run_id
    paths = [folder, folder / 'run.json', folder / 'coverage.json']
    if any(linked(path) for path in paths):
        raise ValueError('Linked inventory rejected')
    manifest, coverage = [json.loads(path.read_text(encoding='utf-8-sig')) for path in paths[1:]]
    if (manifest.get('schema_version') != 1 or coverage.get('schema_version') != 1
            or manifest.get('status') not in {'completed', 'partial'}
            or manifest.get('stages', {}).get('inventory') != 'completed'):
        raise ValueError('Comparison requires completed inventories')
    entries = {}
    for entry in manifest['inventory']:
        path = relative_path(entry['path']).as_posix()
        digest = entry.get('sha256')
        if (path in entries or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                or type(entry.get('lines')) is not int or entry['lines'] < 0):
            raise ValueError('Malformed inventory evidence')
        entries[path] = {'path': path, 'sha256': digest, 'line_count': entry['lines']}
    if sorted(entries) != sorted(manifest['inspected_files']):
        raise ValueError('Inventory and inspected paths disagree')
    hidden = set()
    directories = set()
    for field in ('excluded_files', 'uninspected_files'):
        if not isinstance(coverage[field], list):
            raise ValueError('Malformed inventory scope')
        for label in coverage[field]:
            path = relative_path(label, directory=True)
            (directories if label.endswith('/') else hidden).add(path.as_posix())
    return manifest, entries, hidden, directories


def obscured(label, hidden, directories):
    return label in hidden or any(parent.as_posix() in directories for parent in PurePosixPath(label).parents)


def review_area(label):
    parts = PurePosixPath(label).parts
    if parts[:2] == ('backend', 'app') and len(parts) > 3 and parts[2] == 'modules':
        return '/'.join(parts[:4])
    return parts[0]


def compare(config, baseline_id, current_id):
    _, source, output = configuration(config)
    if baseline_id == current_id:
        raise ValueError('Choose two distinct runs')
    if any(linked(path) for path in (output, *output.parents)):
        raise ValueError('Linked output rejected')
    before, old, old_hidden, old_dirs = load_inventory(output, baseline_id)
    after, new, new_hidden, new_dirs = load_inventory(output, current_id)
    if (before.get('source_root') != str(source) or after.get('source_root') != str(source)
            or before['config'] != after['config']
            or not before.get('scanner_version')
            or before['scanner_version'] != after.get('scanner_version')):
        raise ValueError('Incompatible source, scope policy or scanner version')

    counts = dict.fromkeys(('added', 'removed', 'modified', 'unchanged', 'unknown'), 0)
    changes = []
    areas = {}
    for label in sorted(old.keys() | new.keys()):
        previous, current = old.get(label), new.get(label)
        if previous and current:
            status = 'unchanged' if previous['sha256'] == current['sha256'] else 'modified'
        elif previous:
            status = 'unknown' if obscured(label, new_hidden, new_dirs) else 'removed'
        else:
            status = 'unknown' if obscured(label, old_hidden, old_dirs) else 'added'
        counts[status] += 1
        if status != 'unchanged':
            areas.setdefault(review_area(label), []).append(len(changes))
            changes.append({'path': label, 'status': status, 'before': previous, 'after': current})

    report = {
        'schema_version': 1,
        'baseline_run': baseline_id,
        'current_run': current_id,
        'baseline_revision': before.get('source_revision'),
        'current_revision': after.get('source_revision'),
        'baseline_declared_revision': before.get('declared_revision'),
        'current_declared_revision': after.get('declared_revision'),
        'counts': counts,
        'changes': changes,
        'review_actions': [
            {'id': f'REVIEW-{i:03}', 'area': area,
             'counts': dict(Counter(changes[index]['status'] for index in indexes)),
             'status': 'review_required', 'intent': 'Assess impact before proposing implementation',
             'acceptance': 'Cite current paths and line ranges, trace callers and security controls, and reconcile relevant audit findings.',
             'change_indexes': indexes}
            for i, (area, indexes) in enumerate(sorted(areas.items()), 1)
        ],
        'scope': {
            'baseline_unavailable': sorted(old_hidden | {path + '/' for path in old_dirs}),
            'current_unavailable': sorted(new_hidden | {path + '/' for path in new_dirs}),
        },
        'limitations': [
            'Counts describe inventoried paths. Renames may appear as removal and addition.',
            'Local inventories describe working directories. A null revision is unverified.',
            'Review areas are inferred from paths. Runtime impact, architecture, security and audit remediation require semantic review.',
            'Paths unavailable in both runs do not have a content comparison.',
        ],
    }
    destination = output / current_id / f'impact-from-{baseline_id}.json'
    if (destination.exists() or destination.is_symlink()) and linked(destination):
        raise ValueError('Linked impact output rejected')
    save(destination, report)
    return destination

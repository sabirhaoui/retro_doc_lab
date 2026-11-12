"""Summarize admitted source metadata without copying source contents."""
from collections import Counter
from pathlib import PurePosixPath


ENTRYPOINT_NAMES = {
    '__main__.py', 'main.py', 'app.py', 'asgi.py', 'wsgi.py', 'worker.py',
    'manage.py', 'cli.py', 'celery_app.py',
}
CONFIG_NAMES = {
    'pyproject.toml', 'requirements.txt', 'requirements-dev.txt',
    'alembic.ini', 'Dockerfile', 'docker-compose.yml', 'compose.yml',
    'Makefile', 'package.json',
}


def characterize(entries, excluded, unread, static_audit=None):
    extensions = Counter(PurePosixPath(entry['path']).suffix.lower() or '[sans extension]'
                         for entry in entries)
    roots = Counter(entry['path'].split('/', 1)[0] for entry in entries)
    python_entries = [entry for entry in entries if entry['path'].lower().endswith('.py')]
    entrypoints = []
    configs = []
    for entry in entries:
        path = PurePosixPath(entry['path'])
        if path.name in ENTRYPOINT_NAMES or path.name == 'Dockerfile' or 'scripts' in path.parts:
            entrypoints.append({
                'path': entry['path'],
                'sha256': entry['sha256'],
                'lines': entry['lines'],
                'reason': 'nom ou emplacement candidat; execution non verifiee',
            })
        if path.name in CONFIG_NAMES or path.name.startswith(('requirements', 'alembic')):
            configs.append({
                'path': entry['path'],
                'sha256': entry['sha256'],
                'lines': entry['lines'],
            })

    return {
        'schema_version': 1,
        'status': 'partial',
        'inventory': {
            'admitted_files': len(entries),
            'admitted_bytes': sum(entry['bytes'] for entry in entries),
            'excluded_entries': len(excluded),
            'uninspected_entries': len(unread),
            'python_files': len(python_entries),
            'python_lines': sum(entry['lines'] for entry in python_entries),
            'classes': static_audit.class_count if static_audit else None,
            'functions': sum(len(rows) for rows in static_audit.functions.values()) if static_audit else None,
            'call_sites': len(static_audit.calls) if static_audit else None,
            'route_declarations': len(static_audit.routes) if static_audit else None,
            'extensions': dict(sorted(extensions.items())),
            'top_level_roots': dict(sorted(roots.items())),
        },
        'frameworks_observed': sorted(static_audit.frameworks) if static_audit else [],
        'entrypoints': sorted(entrypoints, key=lambda row: row['path']),
        'configuration_candidates': sorted(configs, key=lambda row: row['path']),
        'parse_failures': sorted(static_audit.parse_failures) if static_audit else [],
        'limitations': [
            'Les noms et imports identifient des candidats; ils ne prouvent pas les points d entree actifs.',
            'Les configurations sont referencees par chemin, sans exposer leurs valeurs.',
            'Le perimetre exclu ou non inspecte reste inconnu.',
        ],
    }

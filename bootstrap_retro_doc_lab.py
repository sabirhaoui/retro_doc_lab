#!/usr/bin/env python3
"""Offline bootstrap from this lab distribution; existing files are never replaced."""
import argparse
from pathlib import Path
import shlex
import sys


def bootstrap(parent):
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11+ requis (tomllib)')
    import venv  # Check the standard prerequisite; do not create or activate implicitly.
    source = Path(__file__).resolve().parent
    root = Path(parent).resolve() / 'retro_doc_lab'
    paths = [Path(name) for name in ('README.md', 'pyproject.toml', 'bootstrap_retro_doc_lab.py',
             'docs/architecture.md', 'docs/OUTPUT_CONTRACT.md', 'profiles/project-twin.toml')]
    for folder, pattern in [('src/retro_doc_agent', '*.py'), ('src/retro_doc_lab', '*.py'),
                            ('skills', 'SKILL.md'), ('examples/fastapi-angular', '*')]:
        paths.extend(p.relative_to(source) for p in (source / folder).rglob(pattern) if p.is_file())
    # Validate templates before creating any destination.
    if not all((source / p).is_file() for p in paths):
        raise RuntimeError('Distribuer le script avec src, docs, profiles et skills du lab')
    root.mkdir(parents=True, exist_ok=True)
    created = 0
    for relative in sorted(set(paths)):
        destination = root / relative
        if destination.exists():
            continue
        # Existing parent links may not redirect writes outside the configured destination.
        if root not in destination.resolve().parents:
            raise ValueError('Lien de destination hors du lab')
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open('xb') as stream:
                stream.write((source / relative).read_bytes())
            created += 1
        except FileExistsError:
            pass
    print(f'Lab: {root}; fichiers crees: {created}; fichiers existants preserves.')
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    print('\nWindows PowerShell:')
    print('Set-Location ' + q(root))
    print('& ' + q(sys.executable) + ' -m venv .venv')
    print('. .\\.venv\\Scripts\\Activate.ps1')
    print('$env:PYTHONPATH = "$PWD\\src"')
    print('python -B -m retro_doc_lab scan --repo C:\\chemin\\project-twin --profile profiles/project-twin.toml --out output/twin-001')
    print('\nLinux:')
    print('cd ' + shlex.quote(str(root)))
    print('python3 -m venv .venv')
    print('. .venv/bin/activate')
    print('export PYTHONPATH="$PWD/src"')
    print('python -B -m retro_doc_lab scan --repo /chemin/project-twin --profile profiles/project-twin.toml --out output/twin-001')
    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, default=Path.cwd())
    args = parser.parse_args()
    bootstrap(args.parent)


if __name__ == '__main__':
    main()

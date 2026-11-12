"""Offline static scan CLI. Does not load anything from the target repository."""
import argparse
import ast
from pathlib import Path
import sys
import tomllib
from .inventory import inventory, plan_batches
from .model import Model, dump
from .analyzers import python_api, web_infra
from .resolution import resolve
from .renderers.markdown import render


LIMITATIONS = [
    'Analyse statique partielle; aucune preuve de couverture complete.',
    'TypeScript extrait par motifs, sans verification des types; liens ecran-service non resolus.',
    'Montages FastAPI conditionnels et imports dynamiques non interpretes.',
    'Compose: services de premier niveau seulement; ancres YAML et substitutions non resolues.',
    'Caddy: directives detectees, selection des sites et reecritures non resolues.',
    'Proxy JSON simple seulement; activation par environnement non etablie.',
    'Etats metier, transitions interprocedurales, retry et reprises non reconstruits.',
    'Detection de secrets heuristique; aucun extrait source ni valeur de configuration publie.',
    'Exclusions et budgets bornent la portee; documentation historique non comparee.',
    'Mermaid: structure generee, validation par parseur a effectuer.',
]


def scan(repo, out, profile=None):
    repo, out = Path(repo).resolve(), Path(out).resolve()
    if not repo.is_dir():
        raise ValueError('Le depot doit etre un dossier existant')
    if out == repo or repo in out.parents or out in repo.parents:
        raise ValueError('La sortie doit etre separee du depot cible')
    if out.exists():
        raise ValueError('Choisir un dossier de sortie neuf')
    config = {}
    if profile:
        with Path(profile).open('rb') as stream:
            config = tomllib.load(stream)
    excludes = config.get('exclude', [])
    if not isinstance(excludes, list) or not all(isinstance(x, str) for x in excludes):
        raise ValueError('exclude doit etre une liste de motifs')
    bounds = config.get('limits', {})
    for key, value in bounds.items():
        if key not in {'max_bytes', 'max_total', 'max_files'} or type(value) is not int or value < 1:
            raise ValueError('Limites invalides')
    entries, texts, excluded, unread = inventory(repo, excludes, **bounds)
    batching = config.get('batches', {})
    if not isinstance(batching, dict) or set(batching) - {'max_bytes', 'max_files'}:
        raise ValueError('batches doit definir max_bytes et max_files')
    batch_bytes = batching.get('max_bytes', 2000000)
    batch_files = batching.get('max_files', 25)
    if type(batch_bytes) is not int or batch_bytes < bounds.get('max_bytes', 1000000):
        raise ValueError('batches.max_bytes doit etre >= limits.max_bytes')
    if type(batch_files) is not int or batch_files < 1:
        raise ValueError('batches.max_files doit etre un entier positif')
    model = Model(entries)
    model.constants = {}
    model.pending_calls = []
    model.texts = texts
    for path, text in texts.items():
        if not path.endswith('.py'):
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and python_api.literal(node.value) is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        model.constants[python_api.module(path) + '.' + target.id] = (
                            python_api.literal(node.value), [model.evidence(path, node.lineno, node.end_lineno)])
    model.limitations.extend(LIMITATIONS)
    components = config.get('components', {})
    if not isinstance(components, dict) or not all(isinstance(x, str) for x in components.values()):
        raise ValueError('components doit associer des noms a des chemins relatifs')
    for name, prefix in components.items():
        if Path(prefix).is_absolute() or '..' in Path(prefix).parts:
            raise ValueError('Chemin de composant non relatif')
    for path, text in texts.items():
        area = next((name for name, prefix in components.items() if path.startswith(prefix.rstrip('/') + '/')), path.split('/')[0])
        model.add('component', path, path, [model.evidence(path)], area=area,
                  responsibility='non etablie', entrypoint=Path(path).name in {'main.py', '__main__.py', 'main.ts', 'Dockerfile', 'Caddyfile'})
        if path.endswith('.py'):
            python_api.analyze(model, path, text)
        web_infra.analyze(model, path, text)
    batches = plan_batches(entries, batch_bytes, batch_files, components)
    resolve(model)
    model.validate()
    # A second bounded read verifies admitted sources have not drifted during analysis.
    after, _, after_excluded, after_unread = inventory(repo, excludes, **bounds)
    if entries != after or excluded != after_excluded or unread != after_unread:
        raise ValueError('Les sources admissibles ont change pendant le scan')
    out.mkdir(parents=True)
    manifest = {'files': entries, 'excluded': excluded, 'unreadable': unread,
                'batch_limits': {'max_bytes': batch_bytes, 'max_files': batch_files},
                'batches': batches,
                'source_revision': None, 'dirty': 'unknown', 'unchanged_admitted_scope': True,
                'limitations': ['Fichiers exclus non ouverts; leur integrite ne peut etre attestee.']}
    render(model, out, manifest)
    dump(out / 'run.json', {'schema_version': 2, 'status': 'partial', 'network': 'disabled',
                          'source_access': 'read-only', 'source_revision': None,
                          'inspected_files': [x['path'] for x in entries], 'limitations': LIMITATIONS})
    return model, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('scan')
    command.add_argument('--repo', required=True, type=Path)
    command.add_argument('--out', required=True, type=Path)
    command.add_argument('--profile', type=Path)
    args = parser.parse_args(argv)
    try:
        model, manifest = scan(args.repo, args.out, args.profile)
    except (ValueError, OSError, RecursionError) as error:
        print('Scan refuse ou impossible: ' + type(error).__name__, file=sys.stderr)
        return 2
    print(f"Scan partiel: {len(manifest['files'])} fichiers, {len(manifest['batches'])} lots, "
          f"{len(model.items)} elements. Sortie: {args.out}")
    return 0

"""Bounded local or opt-in GitHub preparation; never executes inspected source."""
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path

STAGES = ('inventory', 'architecture', 'workflows', 'documentation', 'diagrams', 'coverage')
PHASES = ('analyzer', 'audit', 'sequences', 'reporter')
logger = logging.getLogger(__name__)
EXCLUDE = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'dist', 'build', '.aws', '.ssh'}
SECRET = re.compile(r'(^\.env(?:\.|$)|secret|credential|password|token|\.(?:pem|key|p12|pfx)$)', re.I)
EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.md', '.rst', '.toml', '.json', '.yaml', '.yml', '.sql', '.html', '.css', '.sh', '.ps1'}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def save(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode='w', encoding='utf-8', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.close()
            temporary.replace(path)
        finally:
            stream.close()
            temporary.unlink(missing_ok=True)

def configuration(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    root = path.parent.parent
    remote = cfg.get('github_repository')
    if cfg.get('source_access') != 'read-only' or cfg.get('network') not in {'disabled', 'github'}:
        raise ValueError('Read-only source and disabled/github network required')
    if remote and (cfg.get('network') != 'github' or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', remote)):
        raise ValueError('GitHub repository must be owner/name with network=github')
    source = Path(cfg.get('source_root') or '')
    if not remote and (not source.is_absolute() or not source.is_dir()):
        raise ValueError('source_root must be an existing absolute directory')
    source = source.resolve()
    value = Path(cfg['output_root'])
    output = (root / value).resolve()
    if value.is_absolute() or root not in output.parents:
        raise ValueError('output_root must remain inside the lab')
    if not remote and (source == root or source in root.parents or root in source.parents):
        raise ValueError('Source must be separate from the lab')
    for field in ('max_file_bytes', 'max_total_bytes', 'max_files'):
        if type(cfg.get(field, 1)) is not int or cfg.get(field, 1) < 1:
            raise ValueError('Bounds must be positive integers')
    if not isinstance(cfg.get('exclude'), list) or not all(isinstance(x, str) for x in cfg['exclude']):
        raise ValueError('Invalid exclusions')
    if cfg.get('skills') != list(STAGES):
        raise ValueError('Unsupported skill order')
    return cfg, ('github:' + remote if remote else source), output

def linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)

def excluded(path, patterns):
    return any(part in EXCLUDE or SECRET.search(part) or any(fnmatch.fnmatchcase(part, pat) for pat in patterns) for part in path.parts)

def inventory(source, cfg, inspect=None):
    entries, omitted, unread = [], [], []
    budget = cfg.get('max_total_bytes', 10_000_000)

    def record_unreadable_directory(error):
        if not error.filename or Path(error.filename) == source:
            raise error
        unread.append(Path(error.filename).relative_to(source).as_posix() + '/')

    for directory, dirs, files in os.walk(source, followlinks=False, onerror=record_unreadable_directory):
        base = Path(directory)
        for name in sorted(dirs):
            p = base / name
            if excluded(p.relative_to(source), cfg['exclude']) or linked(p):
                dirs.remove(name)
                omitted.append(p.relative_to(source).as_posix() + '/')
        dirs.sort()
        for name in sorted(files):
            p = base / name
            label = p.relative_to(source).as_posix()
            if excluded(p.relative_to(source), cfg['exclude']) or linked(p):
                omitted.append(label)
                continue
            size = p.stat().st_size
            if (p.suffix.lower() not in EXTENSIONS and name not in {'Dockerfile', 'Makefile'}) or size > cfg['max_file_bytes'] or size > budget or len(entries) >= cfg.get('max_files', 2000):
                unread.append(label)
                continue
            with p.open('rb') as stream:
                raw = stream.read(cfg['max_file_bytes'] + 1)
            if len(raw) > cfg['max_file_bytes'] or len(raw) > budget or b'\x00' in raw:
                unread.append(label)
                continue
            budget -= len(raw)
            entries.append({'path': label, 'sha256': hashlib.sha256(raw).hexdigest(), 'lines': len(raw.decode('utf-8', errors='replace').splitlines()), 'bytes': len(raw), 'documentation': p.suffix.lower() in {'.md', '.rst'}})
            if inspect:
                inspect(entries[-1], raw)
    return entries, omitted, unread

def validate(run):
    meta = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    coverage = json.loads((run / 'coverage.json').read_text(encoding='utf-8'))
    indexed = {e['path']: e for e in meta['inventory']}
    errors = []
    citations = []
    for item in coverage['items']:
        if item['status'] not in {'covered', 'partial', 'missing', 'stale', 'unknown'}:
            errors.append('Invalid coverage status')
        if item['status'] != 'unknown' and not item.get('rationale'):
            errors.append('Semantic classification requires rationale')
        citations.extend(item['evidence'])
    diagrams = ['architecture', 'workflow']
    audit_path = run / 'static-audit.json'
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding='utf-8'))
        for rows in audit['signals'].values():
            citations.extend(rows)
        citations.extend(audit['route_bodies'])
        citations.extend(route['evidence'] for route in audit.get('routes', []))
        citations.extend(call['evidence'] for call in audit.get('calls', []))
        if any(route['handler_path'] not in indexed for route in audit.get('routes', [])):
            errors.append('Invalid route target')
        if any(call.get('target_path') not in indexed for call in audit.get('calls', [])
               if call.get('target_path')):
            errors.append('Invalid call target')
        for edge in audit['dependencies']:
            citations.extend(edge['evidence'])
        diagrams.append('security')
    sequence_index = run / 'sequence-index.json'
    if sequence_index.exists():
        sequences = json.loads(sequence_index.read_text(encoding='utf-8'))
        for item in sequences.get('sequences', []):
            citations.append(item['route_evidence'])
            citations.extend(item['call_evidence'])
        for diagram in sorted((run / 'diagrams' / 'sequences').glob('*.mmd')):
            if not diagram.read_text(encoding='utf-8').startswith('sequenceDiagram\n'):
                errors.append('Invalid sequence diagram envelope')
    for evidence in citations:
        e = indexed.get(evidence['path'])
        if (not e or evidence['sha256'] != e['sha256']
                or not 1 <= evidence['start_line'] <= evidence['end_line'] <= e['lines']
                or ('target_path' in evidence and evidence['target_path'] not in indexed)):
            errors.append('Invalid citation')
    for name in diagrams:
        text = (run / 'diagrams' / (name + '.mmd')).read_text(encoding='utf-8')
        if not text.startswith(('flowchart ', 'sequenceDiagram\n')):
            errors.append('Invalid diagram envelope')
    result = {'valid': not errors, 'errors': errors, 'semantic_review': 'pending', 'mermaid': {'parser': None, 'status': 'unvalidated'}}
    save(run / 'validation.json', result)
    return result

def selected_phases(steps):
    if steps is None:
        return set(PHASES)
    if not steps or any(step not in PHASES for step in steps):
        raise ValueError('At least one valid pipeline step is required')
    selected = set(steps)
    if 'reporter' in selected:
        selected.update(PHASES)
    if 'sequences' in selected:
        selected.update({'analyzer', 'audit'})
    if 'audit' in selected:
        selected.add('analyzer')
    return selected


def execute(config, run_id, resume=False, tag=None, commit=None, baseline_run=None, local_revision=None,
            steps=None, verbose=False):
    cfg, source, output = configuration(config)
    from .revisions import SCANNER_VERSION, scan
    from .static_audit import StaticAudit
    remote = bool(cfg.get('github_repository'))
    if remote and steps is not None:
        raise ValueError('Selectable analysis phases require a local source')
    phases = selected_phases(steps) if not remote else set()
    if local_revision is not None and (remote or not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', local_revision)):
        raise ValueError('A declared local revision must be a full Git hash in local mode')
    if remote and (bool(tag) == bool(commit)):
        raise ValueError('GitHub scans require exactly one --tag or --commit')
    if not remote and (tag or commit or baseline_run):
        raise ValueError('Revision selection and baseline reuse require github_repository')
    if commit and not re.fullmatch(r'[0-9a-fA-F]{40}', commit):
        raise ValueError('Commit must be a full SHA-1')
    if tag is not None and (not tag or len(tag) > 255 or any(ord(c) < 32 for c in tag)):
        raise ValueError('Invalid tag')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', run_id):
        raise ValueError('Invalid run ID')
    output.mkdir(parents=True, exist_ok=True)
    if any(linked(p) for p in [output, *output.parents]):
        raise ValueError('Output contains links')
    baseline = None
    if baseline_run:
        if baseline_run == run_id or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', baseline_run):
            raise ValueError('Invalid baseline run ID')
        baseline_path = output / baseline_run
        if linked(baseline_path) or linked(baseline_path / 'run.json'):
            raise ValueError('Linked baseline rejected')
        baseline = json.loads((baseline_path / 'run.json').read_text(encoding='utf-8'))
        if (baseline.get('config') != cfg or baseline.get('scanner_version') != SCANNER_VERSION
                or baseline.get('status') not in {'partial', 'completed'}
                or baseline.get('stages', {}).get('inventory') != 'completed'):
            raise ValueError('Incompatible baseline')
        for entry in baseline.get('inventory', []):
            if (not isinstance(entry.get('path'), str) or type(entry.get('bytes')) is not int
                    or type(entry.get('lines')) is not int or entry['lines'] < 0 or entry['bytes'] < 0
                    or not re.fullmatch('[0-9a-f]{64}', entry.get('sha256', ''))
                    or type(entry.get('documentation')) is not bool):
                raise ValueError('Malformed baseline inventory')
    run = output / run_id
    if run.exists() and (linked(run) or not resume):
        raise ValueError('Run exists; choose a new ID or explicitly resume')
    run.mkdir(exist_ok=True)
    if any(linked(p) for p in run.rglob('*')):
        raise ValueError('Run contains links; refusing writes')
    previous = None
    if resume:
        previous = json.loads((run / 'run.json').read_text(encoding='utf-8'))
        if previous['source_root'] != str(source) or previous['config'] != cfg or previous['status'] == 'completed':
            raise ValueError('Resume requires unchanged configuration and unfinished run')
    meta = {'schema_version': 1, 'status': 'running', 'source_root': str(source), 'source_revision': None, 'dirty': None, 'started_at': now(), 'finished_at': None, 'inspected_files': [], 'inventory': [], 'errors': [], 'config': cfg, 'stages': {s: 'pending' for s in STAGES}, 'limitations': [
        'Static inventory only; architecture, call chains and historical findings require semantic review.',
        'Revision and dirty state unknown: no repository commands executed.',
        'No model integration or network calls; source contents are not emitted.',
        'Mermaid parser unavailable; diagrams unvalidated.',
        'OS isolation is required for hostile sources; this is not a sandbox.',
        'Concurrent changes are not an atomic snapshot.']}
    meta['pipeline_steps'] = sorted(phases)
    if previous:
        if previous.get('pipeline_steps', sorted(phases)) != sorted(phases):
            raise ValueError('Resume requires unchanged selected steps')
        if previous.get('declared_revision') != local_revision:
            raise ValueError('Resume requires unchanged declared revision')
        if previous.get('revision_selector') != {'tag': tag, 'commit': commit} or previous.get('baseline_run') != baseline_run:
            raise ValueError('Resume requires unchanged revision and baseline')
        if remote:
            checkpoint = scan(cfg, tag, commit, baseline)
            if checkpoint[3] != previous.get('source_revision'):
                raise ValueError('Revision changed since checkpoint; create a new run')
            entries = checkpoint[0]
        else:
            entries = inventory(source, cfg)[0]
        if previous.get('inventory') != entries:
            raise ValueError('Source changed since checkpoint; create a new run')
    if local_revision:
        meta['declared_revision'] = local_revision
    save(run / 'run.json', meta)
    try:
        static_audit = None
        meta.update(scanner_version=SCANNER_VERSION, revision_selector={'tag': tag, 'commit': commit}, baseline_run=baseline_run)
        logger.info('Phase inventory: starting')
        if remote:
            entries, omitted, unread, revision, delta = scan(cfg, tag, commit, baseline)
            meta.update(source_revision=revision, dirty=False, incremental=delta)
            meta['limitations'] = [s for s in meta['limitations'] if not s.startswith(('Revision and', 'Concurrent changes', 'No model'))]
            meta['limitations'] += ['GitHub immutable tree inventory; excluded and bounded files are not downloaded. No working checkout is created.',
                                    'Unchanged blob inventory reused only; aggregate reports regenerated and semantic coverage remains unknown.',
                                    'No model integration; only GitHub API requests, no source uploads.']
        else:
            static_audit = StaticAudit()
            entries, omitted, unread = inventory(source, cfg, static_audit.inspect)
        meta['inventory'] = entries
        meta['inspected_files'] = [e['path'] for e in entries]
        meta['stages']['inventory'] = 'completed'
        logger.info('Phase inventory: %d files, %d excluded, %d uninspected',
                    len(entries), len(omitted), len(unread))
        save(run / 'run.json', meta)
        docs = [e['path'] for e in entries if e['documentation']]
        items = [{'id': e['path'], 'status': 'unknown', 'evidence': [] if not e['lines'] else [{'path': e['path'], 'start_line': 1, 'end_line': e['lines'], 'sha256': e['sha256']}], 'documentation': [], 'rationale': 'Inventory only; semantic documentation comparison pending.'} for e in entries]
        save(run / 'coverage.json', {'schema_version': 1, 'items': items, 'existing_documentation': docs, 'excluded_files': omitted, 'uninspected_files': unread})
        (run / 'diagrams').mkdir(exist_ok=True)
        (run / 'diagrams/architecture.mmd').write_text('flowchart LR\n  A[Inspected scope] --> B[Architecture unverified]\n', encoding='utf-8')
        (run / 'diagrams/workflow.mmd').write_text('sequenceDiagram\n  participant R as Reviewer\n  participant S as Static inventory\n  R->>S: Review required\n', encoding='utf-8')
        characterization = None
        if 'analyzer' in phases:
            from .analyzer import characterize
            logger.info('Phase analyzer: starting')
            characterization = characterize(entries, omitted, unread, static_audit)
            save(run / 'characterization.json', characterization)
            meta['stages']['architecture'] = 'review_required'
            logger.info('Phase analyzer: %d framework imports, %d entrypoint candidates',
                        len(characterization['frameworks_observed']), len(characterization['entrypoints']))
        if 'audit' in phases:
            from .audit import run as run_audit
            logger.info('Phase audit: starting')
            run_audit(static_audit, run, meta, omitted, unread)
            meta['stages']['workflows'] = 'review_required'
            logger.info('Phase audit: %d routes, %d call sites',
                        len(static_audit.routes), len(static_audit.calls))
        if 'sequences' in phases:
            from .sequences import generate
            logger.info('Phase sequences: starting')
            generated_sequences = generate(run)
            meta['stages']['diagrams'] = 'unvalidated'
            logger.info('Phase sequences: %d diagrams generated', len(generated_sequences))
        if 'reporter' in phases:
            from .reporter import render
            logger.info('Phase reporter: starting')
            render(run)
            meta['stages']['documentation'] = 'review_required'
        text = f'# Retrospective documentation checkpoint\n\nObserved scope: {len(entries)} bounded files; {len(docs)} existing documentation candidates.\n\n'
        if remote:
            text += f"Observed commit: {meta['source_revision']}. Reused inventory entries: {len(meta['incremental']['reused'])}.\n\n"
        elif local_revision:
            text += f"Declared local revision (not verified): {local_revision}.\n\n"
        if static_audit and 'audit' in phases:
            text += ('## Audit statique de la version inspectée\n\n'
                     '- [Architecture](architecture-audit.md)\n'
                     '- [Sécurité](security-audit.md)\n'
                     '- [Registre des preuves](static-audit.json)\n\n'
                     'Les diagrammes représentent les regroupements et signaux observés. '
                     'La qualification des workflows et risques reste ouverte.\n\n')
        else:
            for title in ('Revision', 'Architecture', 'Workflows', 'Interfaces', 'Data', 'Deployment', 'Security observations'):
                text += f'## {title}\nUnknown: semantic evidence review pending.\n\n'
        text += '## Documentation gaps\nAll items remain unknown. Generated files do not establish coverage.\n'
        text += 'Existing baseline absent.\n' if not docs else 'Existing documentation candidates listed in coverage.json; accuracy unverified.\n'
        text += '\n## Limitations\n' + '\n'.join('- ' + s for s in meta['limitations']) + '\n'
        (run / 'state-of-art.md').write_text(text, encoding='utf-8')
        if remote:
            for stage in STAGES[1:]:
                meta['stages'][stage] = 'review_required' if stage != 'diagrams' else 'unvalidated'
        elif 'coverage' in meta['stages']:
            meta['stages']['coverage'] = 'review_required'
        result = validate(run)
        meta['status'] = 'partial' if result['valid'] else 'failed'
        meta['errors'] = result['errors']
    except (OSError, ValueError, KeyError) as exc:
        if verbose:
            logger.exception('Pipeline phase failed')
        meta['status'] = 'failed'
        meta['errors'] = ['Stage failed: ' + type(exc).__name__]
    finally:
        meta['finished_at'] = now()
        save(run / 'run.json', meta)
    return run, 1 if meta['status'] == 'failed' else 3

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent.json')
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--run-id', required=True)
    run.add_argument('--resume', action='store_true')
    revision = run.add_mutually_exclusive_group()
    revision.add_argument('--tag')
    revision.add_argument('--commit')
    revision.add_argument('--local-revision')
    run.add_argument('--baseline-run')
    run.add_argument('--step', action='append', choices=PHASES,
                     help='Run one phase and its prerequisites; repeat to select multiple phases')
    run.add_argument('--verbose', action='store_true', help='Log phase progress and counts')
    comparison = sub.add_parser('compare')
    comparison.add_argument('--baseline-run', required=True)
    comparison.add_argument('--run-id', required=True)
    serve = sub.add_parser('dashboard')
    serve.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if getattr(args, 'verbose', False) else logging.WARNING,
                        format='%(levelname)s %(message)s', force=True)
    try:
        if args.command == 'compare':
            from .impact import compare
            print(compare(args.config, args.baseline_run, args.run_id))
            return 0
        if args.command == 'dashboard':
            from .dashboard import serve_dashboard
            _, _, output = configuration(args.config)
            serve_dashboard(output, args.port)
            return 0
        path, code = execute(args.config, args.run_id, args.resume, args.tag, args.commit, args.baseline_run,
                             args.local_revision, getattr(args, 'step', None), getattr(args, 'verbose', False))
        print(f'{path} (exit {code}; partial means semantic review pending)')
        return code
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Configuration or run rejected: ' + str(exc))
        return 2

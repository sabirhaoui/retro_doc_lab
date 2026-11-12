#!/usr/bin/env python3
"""Check scaffold/configuration or a specific agent run. Never executes the agent."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('retro_doc_lab'))
    p.add_argument('--phase', choices=['preflight', 'postflight'], default='preflight')
    p.add_argument('--run-id', help='Required for postflight; a single directory name')
    p.add_argument('--report', type=Path, help='Optional NEW diagnostic JSON file; no overwrite')
    a = p.parse_args()
    checks = []
    def check(name, ok, detail=''):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
    def load(path):
        return json.loads(path.read_text(encoding='utf-8'))
    root = a.root.resolve()
    code = 0
    try:
        check('python', sys.version_info >= (3, 10), 'Requires Python 3.10+')
        cfg = load(root / 'config/agent.json')
        check('config_schema', cfg.get('schema_version') == 1)
        source = Path(cfg['source_root']) if isinstance(cfg.get('source_root'), str) and cfg['source_root'] else None
        check('source_absolute_existing', source and source.is_absolute() and source.is_dir())
        if source:
            source = source.resolve()
            check('source_separate', source != root and root not in source.parents and source not in root.parents)
        check('read_only_policy', cfg.get('source_access') == 'read-only', 'Policy only; OS enforcement needed')
        check('network_policy', cfg.get('network') == 'disabled', 'Policy only; OS enforcement needed')
        check('exclusions', isinstance(cfg.get('exclude'), list) and '.env' in cfg['exclude'])
        check('file_size_bound', type(cfg.get('max_file_bytes')) is int and cfg['max_file_bytes'] > 0)
        check('batch_limits', type(cfg.get('max_batch_bytes')) is int and
              cfg['max_batch_bytes'] >= cfg.get('max_file_bytes', 0) and
              type(cfg.get('max_batch_files')) is int and cfg['max_batch_files'] > 0)
        skills = cfg.get('skills')
        check('skill_list', isinstance(skills, list) and bool(skills))
        for name in skills if isinstance(skills, list) else []:
            safe = isinstance(name, str) and name not in ('.', '..') and '/' not in name and '\\' not in name
            check('skill:' + str(name), safe and (root / 'skills' / name / 'SKILL.md').is_file())
        for name in ('AGENTS.md', 'docs/OUTPUT_CONTRACT.md', 'docs/IMPLEMENTATION_HANDOFF.md', 'src/retro_doc_agent/__main__.py'):
            check(name, (root / name).is_file())
        output_value = cfg.get('output_root')
        if not isinstance(output_value, str) or not output_value:
            raise ValueError('output_root must be a nonempty relative path')
        output = (root / output_value).resolve()
        check('output_confined', not Path(output_value).is_absolute() and root in output.parents and output != root)
        if a.phase == 'postflight':
            if not a.run_id or a.run_id in ('.', '..') or '/' in a.run_id or '\\' in a.run_id:
                p.error('Postflight requires --run-id with one directory name')
            run_dir = (output / a.run_id).resolve()
            if output not in run_dir.parents or root not in output.parents:
                raise ValueError('Run path escapes output directory')
            for name in ('state-of-art.md', 'coverage.json', 'run.json', 'diagrams/architecture.mmd', 'diagrams/workflow.mmd'):
                target = run_dir / name
                check('artifact:' + name, target.is_file() and target.stat().st_size > 0 and run_dir in target.resolve().parents)
            run = load(run_dir / 'run.json')
            check('run_schema', run.get('schema_version') == 1)
            check('run_completed', run.get('status') == 'completed')
            check('run_source', source and run.get('source_root') == str(source))
            check('revision_recorded', 'source_revision' in run)
            for key in ('inspected_files', 'errors', 'limitations'):
                check('run:' + key, isinstance(run.get(key), list))
            check('no_errors', run.get('errors') == [])
            check('inspected_scope', isinstance(run.get('inspected_files'), list) and bool(run['inspected_files']))
            start = dt.datetime.fromisoformat(run['started_at'].replace('Z', '+00:00'))
            end = dt.datetime.fromisoformat(run['finished_at'].replace('Z', '+00:00'))
            check('timestamps', start.tzinfo is not None and end.tzinfo is not None and end >= start)
            coverage = load(run_dir / 'coverage.json')
            check('coverage_schema', coverage.get('schema_version') == 1)
            items = coverage.get('items')
            check('coverage_items', isinstance(items, list) and bool(items))
            for key in ('excluded_files', 'uninspected_files'):
                check('coverage:' + key, isinstance(coverage.get(key), list))
            valid = {'covered', 'partial', 'missing', 'stale', 'unknown'}
            for i, item in enumerate(items if isinstance(items, list) else []):
                ok = isinstance(item, dict) and bool(item.get('id')) and item.get('status') in valid and isinstance(item.get('evidence'), list) and isinstance(item.get('documentation'), list)
                check(f'coverage_item:{i}', ok)
            check('implementation_declared', cfg.get('implemented') is True, 'Declaration is not execution proof')
        failures = any(not c['ok'] for c in checks)
        code = 1 if failures else (3 if a.phase == 'preflight' and cfg.get('implemented') is not True else 0)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        check('diagnostic_error', False, str(exc))
        code = 2
    result = {'phase': a.phase, 'run_id': a.run_id, 'exit_code': code, 'checks': checks,
              'limitations': ['Does not launch an agent or validate factual coverage, source hashes, or Mermaid grammar.', 'No source file contents, environment variables or credentials are collected.']}
    for c in checks:
        print(f"{'PASS' if c['ok'] else 'FAIL'} {c['check']} {c['detail']}")
    if code == 3:
        print('PENDING: agent implementation is not declared ready.')
    if a.report:
        try:
            with a.report.open('x', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
                f.write('\n')
        except OSError as exc:
            print(f'Cannot create report: {exc}', file=sys.stderr)
            return 2
    return code

if __name__ == '__main__':
    sys.exit(main())

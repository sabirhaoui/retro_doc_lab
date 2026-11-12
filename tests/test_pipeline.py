import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from retro_doc_agent.pipeline import execute, validate, STAGES, main
from retro_doc_agent.dashboard import snapshot, PAGE
from retro_doc_agent.impact import compare

class PipelineTests(unittest.TestCase):
    def setUp(self):
        # Fixtures and all test writes stay inside configured lab output.
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'output')
        self.root = Path(self.temp.name)
        self.lab = self.root / 'lab'
        (self.lab / 'config').mkdir(parents=True)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'app.py').write_text('print("never execute")\n', encoding='utf-8')
        (self.source / 'README.md').write_text('Outdated documentation\n', encoding='utf-8')
        (self.source / '.env.production').write_text('SENSITIVE_TEST_VALUE', encoding='utf-8')
        (self.source / 'large.py').write_text('x' * 300, encoding='utf-8')
        (self.source / 'node_modules').mkdir()
        (self.source / 'node_modules/a.py').write_text('excluded', encoding='utf-8')
        self.config = self.lab / 'config/agent.json'
        self.config.write_text(json.dumps({'source_root': str(self.source), 'output_root': 'output', 'network': 'disabled', 'source_access': 'read-only', 'skills': list(STAGES), 'exclude': ['.env'], 'max_file_bytes': 200}), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_inventory_readonly_exclusions_and_unknown_coverage(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()}
        with patch('subprocess.run', side_effect=AssertionError('No shell')), patch('socket.create_connection', side_effect=AssertionError('No network')):
            run, code = execute(self.config, 'test')
        self.assertEqual(code, 3)
        coverage = json.loads((run / 'coverage.json').read_text())
        self.assertEqual({i['id'] for i in coverage['items']}, {'app.py', 'README.md'})
        self.assertTrue(all(i['status'] == 'unknown' for i in coverage['items']))
        self.assertIn('large.py', coverage['uninspected_files'])
        self.assertIn('.env.production', coverage['excluded_files'])
        self.assertTrue(validate(run)['valid'])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
        self.assertNotIn('SENSITIVE_TEST_VALUE', ''.join(p.read_text() for p in run.rglob('*') if p.is_file()))
        self.assertEqual(snapshot(run.parent)[0]['status'], 'partial')

    def test_collision_traversal_and_resume_drift(self):
        run, _ = execute(self.config, 'test')
        with self.assertRaises(ValueError): execute(self.config, 'test')
        with self.assertRaises(ValueError): execute(self.config, '../escape')
        (self.source / 'app.py').write_text('changed\n')
        with self.assertRaises(ValueError): execute(self.config, 'test', True)

    def test_comparison_keeps_uninspected_paths_out_of_additions_and_removals(self):
        execute(self.config, 'before', local_revision='a' * 40)
        (self.source / 'app.py').write_text('x' * 300, encoding='utf-8')
        (self.source / 'large.py').write_text('now inspectable', encoding='utf-8')
        (self.source / 'README.md').unlink()
        (self.source / 'new.py').write_text('new file', encoding='utf-8')
        current, _ = execute(self.config, 'after')

        report = json.loads(compare(self.config, 'before', 'after').read_text())
        self.assertEqual(report['counts'],
                         {'added': 1, 'removed': 1, 'modified': 0, 'unchanged': 0, 'unknown': 2})
        self.assertEqual(report['baseline_declared_revision'], 'a' * 40)
        self.assertIsNone(report['baseline_revision'])
        self.assertEqual(sum(len(action['change_indexes']) for action in report['review_actions']), 4)
        result = next(run for run in snapshot(current.parent) if run['id'] == 'after')
        self.assertEqual(result['impacts'][0]['counts'], report['counts'])

    def test_invalid_citation_and_diagram(self):
        run, _ = execute(self.config, 'test')
        coverage = json.loads((run / 'coverage.json').read_text())
        coverage['items'][0]['evidence'][0]['end_line'] = 999
        (run / 'coverage.json').write_text(json.dumps(coverage))
        (run / 'diagrams/architecture.mmd').write_text('invalid')
        self.assertFalse(validate(run)['valid'])

    def test_local_scan_builds_audit_without_copying_literal_values(self):
        (self.source / 'app.py').write_text(
            '@router.post("/private-marker")\n'
            'def handler(user=Depends(identity)):\n'
            '    return httpx.get("https://private-marker.invalid", verify=False)\n',
            encoding='utf-8',
        )
        run, code = execute(self.config, 'static')
        self.assertEqual(code, 3)
        report = (run / 'static-audit.json').read_text(encoding='utf-8')
        signals = json.loads(report)['signals']
        self.assertEqual(signals['route'][0]['start_line'], 1)
        self.assertEqual(signals['tls_disabled'][0]['end_line'], 3)
        self.assertNotIn('private-marker', report)
        self.assertIn('1 routes', (run / 'diagrams/workflow.mmd').read_text(encoding='utf-8'))

    def test_selectable_phases_generate_sequences_and_report(self):
        app = self.source / 'backend/app'
        app.mkdir(parents=True)
        (app / 'router.py').write_text(
            'from .service import save_item\n'
            '@router.post("/items")\n'
            'def create_item():\n'
            '    collection.add("item")\n'
            '    return save_item()\n',
            encoding='utf-8',
        )
        (app / 'helpers.py').write_text('def add(value):\n    return value\n', encoding='utf-8')
        (app / 'service.py').write_text(
            'def save_item():\n'
            '    return persist()\n'
            'def persist():\n'
            '    return None\n',
            encoding='utf-8',
        )
        run, code = execute(self.config, 'sequences', steps=['sequences'])
        self.assertEqual(code, 3)
        self.assertTrue((run / 'characterization.json').is_file())
        self.assertTrue((run / 'static-audit.json').is_file())
        self.assertTrue((run / 'sequence-index.json').is_file())
        self.assertFalse((run / 'audit_report.md').exists())
        audit = json.loads((run / 'static-audit.json').read_text(encoding='utf-8'))
        self.assertTrue(all('target_symbol' not in call for call in audit['calls']
                            if call['callee_name'] == 'add'))
        sequence = next((run / 'diagrams/sequences').glob('*.mmd')).read_text(encoding='utf-8')
        self.assertIn('save_item (inféré)', sequence)
        report, code = execute(self.config, 'reporter', steps=['reporter'])
        self.assertEqual(code, 3)
        self.assertTrue((report / 'audit_report.md').is_file())
        self.assertTrue((report / 'sequences.md').is_file())
        self.assertIn('```mermaid', (report / 'audit_report.md').read_text(encoding='utf-8'))

    def test_cli_selected_phase_and_verbose(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', [
            'pipeline.py', '--config', str(self.config), 'run',
            '--run-id', 'cli-audit', '--step', 'audit', '--verbose',
        ]), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main()
        self.assertEqual(code, 3)
        self.assertIn('Phase audit', stderr.getvalue())
        self.assertTrue((self.lab / 'output/cli-audit/static-audit.json').is_file())
        self.assertFalse((self.lab / 'output/cli-audit/sequence-index.json').exists())

    def test_interrupted_stage_records_failure_and_resumes(self):
        with patch('retro_doc_agent.pipeline.validate', side_effect=OSError('interruption')):
            run, code = execute(self.config, 'test')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads((run / 'run.json').read_text())['status'], 'failed')
        self.assertEqual(execute(self.config, 'test', True)[1], 3)

    def test_symlink_excluded(self):
        try: (self.source / 'link.py').symlink_to(self.source / 'app.py')
        except OSError: self.skipTest('Symlink privilege unavailable')
        run, _ = execute(self.config, 'test')
        self.assertIn('link.py', json.loads((run / 'coverage.json').read_text())['excluded_files'])

    def test_dashboard_escapes_data(self):
        self.assertIn('textContent=text', PAGE)
        self.assertNotIn('innerHTML', PAGE)

if __name__ == '__main__':
    unittest.main()

"""Only synthetic data; no target code, test or build hook is executed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from retro_doc_agent.scan import scan

LAB = Path(__file__).resolve().parents[1]


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class StaticScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=LAB / 'output')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, text):
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def example(self):
        for p in (LAB / 'examples/fastapi-angular').rglob('*'):
            if p.is_file():
                self.write(p.relative_to(LAB / 'examples/fastapi-angular'), p.read_text(encoding='utf-8'))

    def test_trace_determinism_and_readonly(self):
        self.example()
        before = hashes(self.repo)
        model, _ = scan(self.repo, self.root / 'first')
        scan(self.repo, self.root / 'second')
        self.assertEqual(hashes(self.root / 'first'), hashes(self.root / 'second'))
        self.assertEqual(before, hashes(self.repo))
        flows = model.select('flow')
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[0]['status'], 'inféré')
        self.assertEqual(model.items[flows[0]['target']]['label'], 'read_item')
        self.assertEqual({e['path'] for e in flows[0]['evidence']},
                         {'backend/main.py', 'frontend/item.component.ts'})
        self.assertTrue(model.select('state'))
        self.assertTrue(model.select('transition'))
        self.assertTrue(any(o['category'] == 'error' for o in model.select('operation')))

    def test_exclusion_and_no_execution(self):
        self.write('.env', 'TOP_SECRET_SENTINEL')
        self.write('node_modules/evil.py', 'raise RuntimeError("executed")')
        self.write('ordinary.py', 'password = "SENSITIVE_SENTINEL"')
        self.write('safe.py', 'raise RuntimeError("must never execute")')
        _, manifest = scan(self.repo, self.root / 'report')
        self.assertEqual([x['path'] for x in manifest['files']], ['safe.py'])
        combined = '\n'.join(p.read_text(encoding='utf-8') for p in (self.root / 'report').rglob('*') if p.is_file())
        self.assertNotIn('SENSITIVE_SENTINEL', combined)
        self.assertNotIn('TOP_SECRET_SENTINEL', combined)

    def test_unknown_invalid_and_output_boundary(self):
        self.write('unknown.txt', 'unknown framework\n')
        self.write('broken.py', 'def :')
        model, _ = scan(self.repo, self.root / 'report')
        self.assertEqual(len(model.select('component')), 2)
        self.assertTrue(any('AST' in x for x in model.limitations))
        with self.assertRaises(ValueError):
            scan(self.repo, self.repo / 'output')
        with self.assertRaises(ValueError):
            scan(self.repo, self.root / 'report')

    def test_ambiguous_and_method(self):
        self.example()
        main = (self.repo / 'backend/main.py').read_text()
        self.write('backend/duplicate.py', main)
        model, _ = scan(self.repo, self.root / 'report')
        self.assertEqual(model.select('flow')[0]['status'], 'non résolu')
        self.assertEqual(len(model.select('flow')[0]['candidates']), 2)

    def test_typescript_members_with_object_parameters(self):
        self.write('service.ts', """import {HttpClient} from '@angular/common/http';
@Injectable({})
export class ApiService {
  list() { return this.http.get('/a'); }
  update(id: string, body: {name: string}) {
    return this.http.patch(`/a/${id}`, body);
  }
}
""")
        model, _ = scan(self.repo, self.root / 'report')
        self.assertEqual([c['member'] for c in model.select('http_call')], ['list', 'update'])

    def test_bootstrap_preserves_existing_files_twice(self):
        spec = importlib.util.spec_from_file_location('lab_bootstrap', LAB / 'bootstrap_retro_doc_lab.py')
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)  # Trusted lab code, never target code.
        parent = self.root / 'installation'
        target = parent / 'retro_doc_lab'
        target.mkdir(parents=True)
        (target / 'README.md').write_text('CUSTOM CONTENT')
        self.assertGreater(bootstrap.bootstrap(parent), 0)
        before = hashes(target)
        self.assertEqual(bootstrap.bootstrap(parent), 0)
        self.assertEqual(before, hashes(target))
        self.assertEqual((target / 'README.md').read_text(), 'CUSTOM CONTENT')


if __name__ == '__main__':
    unittest.main()

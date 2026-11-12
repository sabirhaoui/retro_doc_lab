import base64
import hashlib
import json
import unittest
from unittest.mock import patch

import test_pipeline
from retro_doc_agent.pipeline import execute


class RevisionTests(unittest.TestCase):
    setUp = test_pipeline.PipelineTests.setUp
    tearDown = test_pipeline.PipelineTests.tearDown
    def remote_config(self):
        cfg = json.loads(self.config.read_text())
        cfg.update(network='github', github_repository='example/synthetic')
        self.config.write_text(json.dumps(cfg))

    def api(self, files):
        blobs = {}
        tree = []
        for path, raw in files.items():
            sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            tree.append(dict(path=path, type='blob', mode='100644', size=len(raw), sha=sha))
            blobs[sha] = raw

        def response(repo, route):
            if route.startswith('commits/'):
                return {'sha': 'a' * 40, 'commit': {'tree': {'sha': 'b' * 40}}}
            if route.startswith('git/trees/'):
                return {'tree': tree, 'truncated': False}
            raw = blobs[route.rsplit('/', 1)[1]]
            return {'encoding': 'base64', 'content': base64.b64encode(raw).decode()}
        return response

    def test_incremental_revision(self):
        self.remote_config()
        files = {'same.py': b'x=1\n', 'edit.py': b'y=1\n', 'gone.py': b'z=1\n', '.env': b'NEVER_DOWNLOAD'}
        with patch('retro_doc_agent.revisions.request', side_effect=self.api(files)) as api:
            first, code = execute(self.config, 'first', tag='v1')
            self.assertEqual(code, 3)
            self.assertEqual(sum('git/blobs/' in c.args[1] for c in api.call_args_list), 3)
        files.pop('gone.py')
        files['edit.py'] = b'y=2\n'
        files['new.py'] = b'n=1\n'
        with patch('retro_doc_agent.revisions.request', side_effect=self.api(files)) as api:
            run, code = execute(self.config, 'second', commit='a' * 40, baseline_run='first')
            self.assertEqual(code, 3)
            self.assertEqual(sum('git/blobs/' in c.args[1] for c in api.call_args_list), 2)
        meta = json.loads((run / 'run.json').read_text())
        self.assertEqual(meta['incremental'], dict(reused=['same.py'], unchanged=['same.py'], changed=['edit.py'], added=['new.py'], deleted=['gone.py']))
        self.assertEqual(meta['source_revision'], 'a' * 40)
        self.assertNotIn('NEVER_DOWNLOAD', ''.join(p.read_text() for p in run.rglob('*') if p.is_file()))
        self.assertTrue((first / 'run.json').exists())

    def test_revision_rejections(self):
        self.remote_config()
        with self.assertRaises(ValueError): execute(self.config, 'none')
        with self.assertRaises(ValueError): execute(self.config, 'short', commit='abc')
        with patch('retro_doc_agent.revisions.request', return_value={'sha': 'b' * 40}):
            run, code = execute(self.config, 'mismatch', commit='a' * 40)
        self.assertEqual(code, 1)

    def test_truncated_tree_fails(self):
        self.remote_config()
        with patch('retro_doc_agent.revisions.request', side_effect=[
            {'sha': 'a' * 40, 'commit': {'tree': {'sha': 'b' * 40}}},
            {'truncated': True, 'tree': []}]):
            run, code = execute(self.config, 'truncated', tag='v1')
        self.assertEqual(code, 1)

    def test_incompatible_baseline_and_offline_policy(self):
        self.remote_config()
        with patch('retro_doc_agent.revisions.request', side_effect=self.api({'a.py': b'x\n'})):
            execute(self.config, 'base', tag='v1')
        cfg = json.loads(self.config.read_text())
        cfg['max_file_bytes'] += 1
        self.config.write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            execute(self.config, 'next', tag='v2', baseline_run='base')
        cfg['network'] = 'disabled'
        self.config.write_text(json.dumps(cfg))
        with patch('retro_doc_agent.revisions.request', side_effect=AssertionError('offline')):
            with self.assertRaises(ValueError): execute(self.config, 'offline', tag='v1')

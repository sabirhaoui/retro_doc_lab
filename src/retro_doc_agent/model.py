"""Deterministic evidence model, with no source execution."""
import hashlib
import json


def stable(kind, key):
    return kind + '_' + hashlib.sha256(key.encode()).hexdigest()[:20]


class Model:
    def __init__(self, entries):
        self.entries = {e['path']: e for e in entries}
        self.items = {}
        self.limitations = []

    def evidence(self, path, start=1, end=None):
        entry = self.entries[path]
        return {'path': path, 'start_line': start, 'end_line': end or start,
                'sha256': entry['sha256']}

    def add(self, kind, key, label, evidence, status='observé', **fields):
        ident = stable(kind, key)
        item = dict(id=ident, kind=kind, label=label, status=status,
                    evidence=evidence, **fields)
        self.items[ident] = item
        return item

    def select(self, kind):
        return [x for x in self.items.values() if x['kind'] == kind]

    def validate(self):
        for item in self.items.values():
            assert item['status'] in {'observé', 'inféré', 'non résolu'}
            assert item['evidence'], item['id']
            for ev in item['evidence']:
                entry = self.entries[ev['path']]
                assert 1 <= ev['start_line'] <= ev['end_line'] <= entry['lines']
                assert ev['sha256'] == entry['sha256']
            for field in ('source', 'target'):
                if field in item:
                    assert item[field] in self.items
            for ident in item.get('candidates', []):
                assert ident in self.items

    def export(self):
        self.validate()
        return {'schema_version': 2, 'items': sorted(self.items.values(), key=lambda x: x['id']),
                'limitations': sorted(set(self.limitations))}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')

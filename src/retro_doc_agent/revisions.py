"""Bounded GitHub revision inventory, without checkout or source execution."""
import base64
import hashlib
import json
import os
import re
from pathlib import PurePosixPath
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

SCANNER_VERSION = 1


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('GitHub redirects are disabled')


def request(repository, route):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'retro-doc-lab'}
    token = os.environ.get('RETRO_DOC_GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request('https://api.github.com/repos/' + repository + '/' + route, headers=headers)
    with build_opener(NoRedirect).open(req, timeout=30) as response:
        data = response.read(16_000_001)
    if len(data) > 16_000_000:
        raise ValueError('GitHub response exceeds bound')
    return json.loads(data)


def object_id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('Invalid Git object ID')
    return value


def scan(cfg, tag, commit, baseline):
    from .pipeline import excluded, EXTENSIONS
    repository = cfg['github_repository']
    if bool(tag) == bool(commit):
        raise ValueError('Select exactly one tag or full commit SHA-1')
    selector = object_id(commit.lower()) if commit else 'refs/tags/' + tag
    resolved = request(repository, 'commits/' + quote(selector, safe=''))
    revision = object_id(resolved['sha'])
    if commit and revision != commit.lower():
        raise ValueError('Commit resolution mismatch')
    tree = object_id(resolved['commit']['tree']['sha'])
    result = request(repository, 'git/trees/' + tree + '?recursive=1')
    if result.get('truncated'):
        raise ValueError('Truncated Git tree; refusing incomplete revision')
    entries, omitted, unread, present, reused = [], [], [], [], []
    old = {e['path']: e for e in baseline.get('inventory', [])} if baseline else {}
    budget = cfg.get('max_total_bytes', 10_000_000)
    for item in sorted(result['tree'], key=lambda x: x['path']):
        label = item['path']
        path = PurePosixPath(label)
        if path.is_absolute() or '..' in path.parts or '\\' in label or not path.parts:
            raise ValueError('Unsafe tree path')
        if item['type'] == 'tree':
            continue
        present.append(label)
        if excluded(path, cfg['exclude']):
            omitted.append(label)
            continue
        size = item.get('size', 0)
        if (item.get('mode') not in {'100644', '100755'} or item['type'] != 'blob'
                or (path.suffix.lower() not in EXTENSIONS and path.name not in {'Dockerfile', 'Makefile'})
                or type(size) is not int or size < 0 or size > cfg['max_file_bytes']
                or size > budget or len(entries) >= cfg.get('max_files', 2000)):
            unread.append(label)
            continue
        blob = object_id(item['sha'])
        prior = old.get(label)
        if prior and prior.get('git_blob') == blob and prior['bytes'] == size:
            entries.append({k: prior[k] for k in ('path', 'sha256', 'lines', 'bytes', 'documentation', 'git_blob')})
            reused.append(label)
            budget -= size
            continue
        data = request(repository, 'git/blobs/' + blob)
        if data.get('encoding') != 'base64':
            raise ValueError('Unsupported blob encoding')
        raw = base64.b64decode(data['content'])
        if len(raw) != size or hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + raw).hexdigest() != blob:
            raise ValueError('Blob integrity mismatch')
        if b'\0' in raw:
            unread.append(label)
            continue
        budget -= size
        entries.append({'path': label, 'sha256': hashlib.sha256(raw).hexdigest(),
                        'lines': len(raw.decode('utf-8', errors='replace').splitlines()),
                        'bytes': size, 'documentation': path.suffix.lower() in {'.md', '.rst'}, 'git_blob': blob})
    current = {e['path']: e for e in entries}
    delta = {'reused': reused, 'added': sorted(set(current) - set(old)),
             'changed': sorted(p for p in current.keys() & old.keys() if current[p]['sha256'] != old[p]['sha256']),
             'unchanged': sorted(p for p in current.keys() & old.keys() if current[p]['sha256'] == old[p]['sha256']),
             'deleted': sorted(set(old) - set(present))}
    return entries, omitted, unread, revision, delta

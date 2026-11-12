"""Read-only, bounded inventory. Exclude before opening; never follow links."""
import fnmatch
import hashlib
import os
from pathlib import Path
import re
import stat

EXCLUDE = {'.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__', 'dist',
           'build', '.angular', '.pytest_cache', '.ruff_cache', '.aws', '.ssh',
           'coverage', '.idea', '.vscode', '.next'}
SECRET_NAME = re.compile(r'(^\.env($|\.)|secret|credential|password|token|\.(pem|key|p12|pfx|keystore)$)', re.I)
SECRET_CONTENT = re.compile(r'-----BEGIN .*PRIVATE KEY|(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[=:]\s*[\"\x27]?[A-Za-z0-9+/_.-]{8,}|://[^\s/:]+:[^\s/@]+@|\b(?:ghp_|sk_live_|AKIA)[A-Za-z0-9]{12,}', re.I)
EXTENSIONS = {'.py', '.ts', '.tsx', '.js', '.json', '.toml', '.yaml', '.yml', '.md', '.html', '.sql', '.txt', '.conf'}


def linked(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def inventory(root, excludes=(), max_bytes=1000000, max_total=50000000, max_files=10000):
    entries, texts, excluded, unread = [], {}, [], []
    budget = max_total

    def omit(path):
        rel = path.relative_to(root)
        return any(p in EXCLUDE or SECRET_NAME.search(p) or p.startswith('.test-') for p in rel.parts) or any(
            fnmatch.fnmatchcase(rel.as_posix(), pattern) or any(fnmatch.fnmatchcase(p, pattern) for p in rel.parts)
            for pattern in excludes)

    def walk_error(error):
        unread.append({'path': Path(error.filename).relative_to(root).as_posix(), 'reason': 'directory unreadable'})

    for folder, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        base = Path(folder)
        for name in sorted(dirs):
            p = base / name
            try:
                skip = omit(p) or linked(p)
            except OSError:
                skip = True
            if skip:
                dirs.remove(name)
                excluded.append(p.relative_to(root).as_posix() + '/')
        dirs.sort()
        for name in sorted(files):
            p = base / name
            rel = p.relative_to(root).as_posix()
            try:
                if omit(p) or linked(p):
                    excluded.append(rel)
                    continue
                info = p.stat()
                if not stat.S_ISREG(info.st_mode):
                    unread.append({'path': rel, 'reason': 'not a regular file'})
                    continue
                if p.suffix.lower() not in EXTENSIONS and name not in {'Dockerfile', 'Caddyfile', 'Makefile'}:
                    unread.append({'path': rel, 'reason': 'unsupported format'})
                    continue
                if info.st_size > min(max_bytes, budget) or len(entries) >= max_files:
                    unread.append({'path': rel, 'reason': 'budget'})
                    continue
                with p.open('rb') as stream:
                    raw = stream.read(min(max_bytes, budget) + 1)
                if len(raw) > min(max_bytes, budget):
                    unread.append({'path': rel, 'reason': 'budget'})
                    continue
                budget -= len(raw)
                text = raw.decode('utf-8-sig')
                if '\x00' in text:
                    raise UnicodeError()
                if SECRET_CONTENT.search(text):
                    excluded.append(rel)
                    continue
                entries.append({'path': rel, 'sha256': hashlib.sha256(raw).hexdigest(),
                                'lines': max(1, len(text.splitlines())), 'bytes': len(raw)})
                texts[rel] = text
            except (OSError, UnicodeError):
                unread.append({'path': rel, 'reason': 'unreadable or non UTF-8'})
    return entries, texts, sorted(excluded), sorted(unread, key=lambda x: x['path'])

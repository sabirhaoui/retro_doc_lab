import json
import posixpath
from pathlib import PurePosixPath
import re


def analyze(model, path, text):
    def evidence(match):
        return [model.evidence(path, text.count('\n', 0, match.start()) + 1,
                               text.count('\n', 0, match.end()) + 1)]

    if path.endswith('.ts'):
        # Mask comments without changing offsets; templates remain intentionally limited.
        text = re.sub(r'/\*[\s\S]*?\*/|(?m:^\s*//[^\n]*)', lambda m: re.sub(r'[^\n]', ' ', m.group()), text)
        for match in re.finditer(r'@(Component|Injectable)\s*\([\s\S]*?export\s+class\s+(\w+)', text):
            model.add('angular_component' if match[1] == 'Component' else 'angular_service',
                      path + ':' + match[2], match[2], evidence(match), symbol=match[2])
        for match in re.finditer(r'\bpath\s*:\s*[\"\x27]([^\"\x27]*)[\"\x27]\s*,\s*(?:component|loadComponent)\s*:', text):
            model.add('ui_route', path + ':' + str(match.start()), 'Route Angular', evidence(match), route=match[1])
        # Literal constants resolve simple base URLs, without evaluating TypeScript.
        constants = {}
        for match in re.finditer(r'\b(\w+)\s*(?::\s*string)?\s*=\s*([\"\x27`])([^\n]*?)\2', text):
            constants[match[1]] = (match[3], evidence(match))
        env_import = re.search(r'import\s*\{\s*environment\s*\}\s*from\s*[\"\x27]([^\"\x27]+)[\"\x27]', text)
        if env_import and env_import[1].startswith('.'):
            env_path = posixpath.normpath(posixpath.join(posixpath.dirname(path), env_import[1])) + '.ts'
            env_text = getattr(model, 'texts', {}).get(env_path, '')
            for env_value in re.finditer(r'\b(\w+)\s*:\s*([\"\x27])([^\n]*?)\2', env_text):
                if env_value[3].startswith('/'):
                    constants['environment.' + env_value[1]] = (env_value[3], evidence(env_import) +
                        [model.evidence(env_path, env_text.count('\n', 0, env_value.start()) + 1)])
            for assignment in re.finditer(r'\b(\w+)\s*=\s*(environment\.\w+)\s*;', text):
                if assignment[2] in constants:
                    val, evs = constants[assignment[2]]
                    constants[assignment[1]] = (val, evs + evidence(assignment))
        for _ in range(8):
            changed = False
            for key, (val, evs) in list(constants.items()):
                for expr in re.findall(r'\$\{([^}]+)\}', val):
                    ref = expr.removeprefix('this.')
                    if ref in constants and '${' not in constants[ref][0]:
                        val = val.replace('${' + expr + '}', constants[ref][0])
                        evs = evs + constants[ref][1]
                        changed = True
                constants[key] = (val, evs)
            if not changed:
                break
        for match in re.finditer(r'\b(?:this\.)?(\w+)\.(get|post|put|patch|delete|head|options)\s*(?:<[^;\n]*?>)?\s*\(\s*([\"\x27`])([^\n]*?)\3', text):
            # HTTP-like receiver plus HttpClient import is a candidate, not type checking.
            if not re.search(r'\bHttpClient\b', text):
                continue
            route, proofs = match[4], evidence(match)
            for expr in re.findall(r'\$\{([^}]+)\}', route):
                key = expr.removeprefix('this.')
                if key in constants:
                    route = route.replace('${' + expr + '}', constants[key][0])
                    proofs += constants[key][1]
            # A class member starts at one indentation level; do not let object
            # type braces or multiline parameters merge adjacent method bodies.
            methods = list(re.finditer(r'(?m)^(?:  |\t)(?:(?:public|private|protected|async)\s+)*(\w+)\s*\(', text[:match.start()]))
            model.add('http_call', path + ':' + str(match.start()), match[2].upper(), proofs,
                      status='inféré', method=match[2].upper(), route=route,
                      context=path, receiver=match[1], member=methods[-1][1] if methods else None)
        if '@Component' in text:
            injections = dict(re.findall(r'\b(?:private|public|protected)\s+(?:readonly\s+)?(\w+)\s*:\s*(\w+)', text))
            injections.update(dict(re.findall(r'\b(\w+)\s*=\s*inject\s*\(\s*(\w+)\s*\)', text)))
            for match in re.finditer(r'\bthis\.(\w+)\.(\w+)\s*\(', text):
                if match[1] in injections:
                    model.add('ui_invocation', path + ':' + str(match.start()), match[2], evidence(match),
                              status='non résolu', service=injections[match[1]], member=match[2])
        for match in re.finditer(r'\b(?:this\.)?(state|status|loading|error)\s*(?::\s*[^=;\n]+)?=\s*([\"\x27])([\w -]{1,40})\2|\b(?:this\.)?(loading|error)\s*=\s*(true|false)', text):
            variable = match[1] or match[4]
            value = match[3] or match[5]
            state = model.add('state', path + ':' + variable + ':' + value, variable + '=' + value,
                             evidence(match), domain='interface', entity=path + ':' + variable)
            # Explicit callback markers provide an event; no guessed ordering of states.
            prefix = text[max(0, match.start() - 180):match.start()]
            events = list(re.finditer(r'\b(next|error|complete)\s*:', prefix))
            if events:
                model.add('transition', path + ':' + str(match.start()), 'callback ' + events[-1][1],
                          evidence(match), status='inféré', target=state['id'],
                          event='HTTP callback ' + events[-1][1], condition=None, source_state=None)

    # Technology detections are constrained to executable declarations / manifests.
    patterns = {
        'FastAPI': r'(?m)^\s*(?:from\s+fastapi\b|import\s+fastapi\b|fastapi\s*[=<>~])',
        'Angular': r'[\"\x27]@angular/core[\"\x27]',
        'PostgreSQL': r'(?im)^\s*image:\s*[\"\x27]?postgres[:@\s]|\b(?:postgresql\+\w+|postgresql|postgres)://|(?m:^\s*(?:psycopg\w*(?:\[[\w,]+\])?|asyncpg)\s*[=<>~])|(?m:^\s*from\s+sqlalchemy\.dialects\.postgresql\b)',
        'Celery': r'(?m)^\s*(?:from\s+celery\b|import\s+celery\b|celery\s*[=<>~])',
        'Caddy': r'(?im)^\s*image:\s*[\"\x27]?caddy[:@\s]|(?m:^\s*reverse_proxy\s+)',
    }
    if not path.endswith(('.md', '.html')):
        for technology, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                model.add('technology', path + ':' + technology + ':' + str(match.start()), technology, evidence(match))
    if PurePosixPath(path).name in {'Caddyfile'} or path.endswith('.caddy'):
        for match in re.finditer(r'(?m)^\s*(reverse_proxy|handle_path|uri\s+strip_prefix)\s+([^\s{]+)', text):
            model.add('proxy_rule', path + ':' + str(match.start()), match[1], evidence(match),
                      status='non résolu', directive=match[1],
                      path_pattern=match[2] if match[2].startswith('/') else None)
    if path.endswith(('.yml', '.yaml')) and 'compose' in PurePosixPath(path).name.lower():
        inside = False
        for i, line in enumerate(text.splitlines(), 1):
            if re.match(r'^services:\s*(?:#.*)?$', line):
                inside = True
                continue
            if line and not line.startswith((' ', '#')):
                inside = False
            match = re.match(r'^  ([\w-]+):\s*(?:#.*)?$', line)
            if inside and match:
                model.add('compose_service', path + ':' + match[1], match[1], [model.evidence(path, i)])
    if PurePosixPath(path).name.startswith('proxy') and path.endswith('.json'):
        try:
            config = json.loads(text)
            if not isinstance(config, dict):
                return
            for prefix, value in config.items():
                if isinstance(value, dict):
                    for old, new in value.get('pathRewrite', {}).items():
                        if isinstance(old, str) and isinstance(new, str) and re.fullmatch(r'\^/[\w/-]+', old) and re.fullmatch(r'/[\w/-]*|', new):
                            model.add('rewrite', path + ':' + old, 'proxy pathRewrite',
                                      [model.evidence(path, 1, model.entries[path]['lines'])],
                                      status='inféré', old=old[1:], new=new)
        except (ValueError, AttributeError, TypeError):
            model.limitations.append(path + ': proxy JSON non resolu')

"""Extract auditable static evidence from the exact bytes accepted by inventory."""

import ast
from collections import defaultdict
import re

from .pipeline import save


ARCHITECTURE = {
    'frontend': ('Frontend Angular', r'^frontend/src/'),
    'api': ('Backend et API', r'^backend/app/'),
    'identity': ('Identité et accès', r'(^|/)(identity|auth|permissions)(/|\.)'),
    'studio': ('Studio, jumeaux et graphe', r'/(studio(?:_v2)?|twin_[^/]+|document_graph|retrieval)/'),
    'experimentation': ('Expérimentation', r'/experimentation/'),
    'ai': ('Assystan et IA', r'/(assystan|llm_gateway)/'),
    'connectors': ('Connecteurs et imports', r'/(connectors|unifier_package|packages)/'),
    'data': ('Persistance et migrations', r'(^|/)(migrations|alembic|repositories|models)(/|\.)'),
    'runtime': ('Déploiement et configuration', r'(^|/)(deploy|nginx|docker-compose[^/]*|Dockerfile|requirements[^/]*|package-lock\.json)(/|$)'),
    'ci': ('Intégration et livraison', r'(^|/)(\.github/workflows/|azure-pipelines[^/]*|\.gitlab-ci\.yml)'),
    'quality': ('Tests et observabilité', r'(^|/)(tests|observability|monitoring)(/|\.)|\.spec\.ts$'),
}

SIGNALS = {
    'route': 'Décorateurs de routes HTTP',
    'dependency': 'Dépendances FastAPI déclarées',
    'routers': 'Enregistrement de routeurs',
    'http': 'Appels HTTP candidats',
    'async': 'Soumission de tâches candidates',
    'persistence': 'Opérations de persistance candidates',
}

CONTROLS = {
    'cors_literal': ('Origines CORS littérales', 'Vérifier la configuration effective par environnement.'),
    'tls_disabled': ('Vérification TLS désactivée par un argument littéral', 'Tracer les appelants et les destinations accessibles.'),
    'browser_storage': ('Écritures dans le stockage navigateur', 'Qualifier les données, la durée et les conditions de purge.'),
    'archive': ('Extraction d’archive candidate', 'Vérifier les limites de taille, de nombre et les chemins extraits.'),
    'dependency': ('Dépendances FastAPI déclarées', 'Vérifier authentification, autorisations et isolation des objets.'),
    'http': ('Appels HTTP candidats', 'Tracer la validation des destinations et la gestion des redirections.'),
    'published_port': ('Blocs de publication de ports Compose', 'Vérifier l’interface liée et l’exposition effective.'),
}


def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ''


def call_dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = call_dotted(node.value)
        return prefix + '.' + node.attr if prefix else node.attr
    return ''


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


class StaticAudit:
    def __init__(self):
        self.areas = defaultdict(list)
        self.signals = defaultdict(list)
        self.modules = {}
        self.imports = []
        self.edges = defaultdict(list)
        self.route_bodies = []
        self.routes = []
        self.functions = defaultdict(list)
        self.calls = []
        self.frameworks = set()
        self.class_count = 0
        self.parse_failures = []

    def inspect(self, entry, raw):
        path = entry['path']
        for key, (_, pattern) in ARCHITECTURE.items():
            if re.search(pattern, path, re.I):
                self.areas[key].append(path)
        if path.endswith('.py'):
            try:
                tree = ast.parse(raw)
            except (SyntaxError, ValueError, RecursionError):
                self.parse_failures.append(path)
                return
            module = path.removeprefix('backend/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')
            aliases = {}
            imported_modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    base = node.module or ''
                    imported_modules.add(base.split('.')[0])
                    if node.level:
                        parent = module.split('.')[:-node.level]
                        base = '.'.join(parent + ([base] if base else []))
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = base + '.' + alias.name
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_modules.add(alias.name.split('.')[0])
                        aliases[alias.asname or alias.name.split('.')[0]] = (
                            alias.name if alias.asname else alias.name.split('.')[0])
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    self.imports.append((entry, node.module, node.lineno, node.end_lineno))
                elif isinstance(node, ast.Import):
                    self.imports.extend((entry, alias.name, node.lineno, node.end_lineno) for alias in node.names)
            self.frameworks.update(imported_modules & {
                'fastapi', 'starlette', 'flask', 'django', 'celery', 'sqlalchemy',
                'alembic', 'pytest', 'httpx', 'requests', 'redis', 'asyncpg',
            })
            if path.startswith('backend/app/'):
                self.modules[module] = path

            def collect_functions(body, prefix):
                for child in body:
                    if isinstance(child, ast.ClassDef):
                        collect_functions(child.body, prefix + '.' + child.name)
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbol = prefix + '.' + child.name
                        function = {'symbol': symbol, 'path': path, 'node': child, 'module': module,
                                    'aliases': aliases, 'evidence': self.evidence(entry, child)}
                        self.functions[symbol].append(function)
                        file_functions.append(function)
                        collect_functions(child.body, symbol)

            file_functions = []
            collect_functions(tree.body, module)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.class_count += 1
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                                and decorator.func.attr in {'get', 'post', 'put', 'patch', 'delete', 'options', 'head'}
                                and isinstance(decorator.func.value, ast.Name)
                                and decorator.func.value.id in {'app', 'router'}):
                            self.record('route', entry, decorator.lineno, decorator.end_lineno)
                            self.record_route_body(entry, node)
                            handler = next((symbol for symbol, rows in self.functions.items()
                                            if any(row['node'] is node for row in rows)),
                                           module + '.' + node.name)
                            self.routes.append({
                                'handler_symbol': handler,
                                'handler_path': path,
                                'method': decorator.func.attr.upper(),
                                'route_literal_present': bool(decorator.args and
                                                               isinstance(literal(decorator.args[0]), str)),
                                'route': None,
                                'signals': sorted(self.route_signals(node)),
                                'evidence': self.evidence(entry, decorator),
                            })
                            break
                if isinstance(node, ast.Call):
                    self.inspect_call(entry, node)
            for function in file_functions:
                for call in self.function_calls(function['node']):
                    name = call_dotted(call.func)
                    if not name:
                        continue
                    first, _, rest = name.partition('.')
                    imported = aliases.get(first)
                    target = imported + ('.' + rest if rest else '') if imported else (
                        module + '.' + name if '.' not in name else name)
                    self.calls.append({
                        'caller': function['symbol'],
                        'caller_path': path,
                        'callee_name': name.rsplit('.', 1)[-1],
                        'target_hint': target,
                        'evidence': self.evidence(entry, call),
                    })
        elif path.endswith(('.ts', '.js', '.tsx')):
            for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
                if re.search(r'\b(?:localStorage|sessionStorage)\s*\.\s*setItem\s*\(', line):
                    self.record('browser_storage', entry, number, number)
        elif re.search(r'(^|/)docker-compose[^/]*\.ya?ml$', path):
            for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
                if re.fullmatch(r'\s+ports:\s*(?:#.*)?', line):
                    self.record('published_port', entry, number, number)

    def inspect_call(self, entry, node):
        name = call_name(node.func)
        mapping = {
            'Depends': 'dependency', 'Security': 'dependency', 'include_router': 'routers',
            'apply_async': 'async', 'delay': 'async', 'commit': 'persistence',
            'flush': 'persistence', 'extractall': 'archive',
        }
        if name in mapping:
            self.record(mapping[name], entry, node.lineno, node.end_lineno)
        if name in {'request', 'get', 'post', 'put', 'patch', 'delete', 'Client', 'AsyncClient'}:
            receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
            if call_name(receiver) in {'httpx', 'requests', 'client', 'http_client'}:
                self.record('http', entry, node.lineno, node.end_lineno)
        for keyword in node.keywords:
            if (name in {'request', 'get', 'post', 'put', 'patch', 'delete', 'Client', 'AsyncClient', 'Session'}
                    and keyword.arg == 'verify' and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False):
                self.record('tls_disabled', entry, keyword.lineno, keyword.end_lineno)
            if keyword.arg == 'allow_origins' and isinstance(keyword.value, (ast.List, ast.Tuple)):
                self.record('cors_literal', entry, keyword.lineno, keyword.end_lineno)

    def record_route_body(self, entry, function):
        signals = self.route_signals(function)
        if signals:
            path = entry['path']
            module = path.removeprefix('backend/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')
            self.route_bodies.append({
                'path': path, 'start_line': function.lineno, 'end_line': function.end_lineno,
                'sha256': entry['sha256'], 'handler': module + '.' + function.name,
                'signals': sorted(signals),
            })

    @staticmethod
    def route_signals(function):
        signals = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                name = call_name(node.func)
                if name in {'Depends', 'Security'}:
                    signals.add('dependency')
                if name in {'apply_async', 'delay'}:
                    signals.add('async')
                if name in {'flush', 'commit'}:
                    signals.add('persistence')
        return signals

    @staticmethod
    def function_calls(function):
        pending = list(reversed(function.body))
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Call):
                yield node
            pending.extend(reversed(list(ast.iter_child_nodes(node))))

    @staticmethod
    def evidence(entry, node):
        return {'path': entry['path'], 'start_line': node.lineno,
                'end_line': getattr(node, 'end_lineno', node.lineno), 'sha256': entry['sha256']}

    def resolve_calls(self):
        for call in self.calls:
            exact = self.functions.get(call['target_hint'], [])
            candidates = exact
            if not candidates and call['target_hint'].startswith(('self.', 'cls.')):
                class_symbol = call['caller'].rsplit('.', 1)[0]
                candidates = self.functions.get(
                    class_symbol + '.' + call['target_hint'].rsplit('.', 1)[-1], [])
            unique = len(candidates) == 1
            call['status'] = 'inféré' if unique else 'non résolu'
            call['candidates'] = sorted({item['symbol'] for item in candidates})
            if unique:
                target = candidates[0]
                call['target_symbol'] = target['symbol']
                call['target_path'] = target['path']

    def record(self, kind, entry, start, end):
        self.signals[kind].append({
            'path': entry['path'], 'start_line': start, 'end_line': end, 'sha256': entry['sha256'],
        })

    def write(self, run, meta, omitted, unread):
        self.resolve_calls()
        area_by_path = {
            path: key for key, paths in self.areas.items()
            if key not in {'api', 'frontend', 'quality'}
            for path in paths
        }
        for entry, imported, start, end in self.imports:
            target = self.modules.get(imported)
            if not target or not entry['path'].startswith('backend/app/'):
                continue
            origin_area = area_by_path.get(entry['path'], 'api')
            target_area = area_by_path.get(target, 'api')
            if origin_area != target_area:
                self.edges[origin_area, target_area].append({
                    'path': entry['path'], 'start_line': start, 'end_line': end,
                    'sha256': entry['sha256'], 'target_path': target,
                })
        for evidence in self.signals.values():
            evidence.sort(key=lambda row: (row['path'], row['start_line'], row['end_line']))
        payload = {
            'schema_version': 1,
            'status': 'review_required',
            'source_root': str(meta.get('source_root') or ''),
            'source_revision': meta.get('source_revision'),
            'declared_revision': meta.get('declared_revision'),
            'scope': {'inspected': len(meta['inventory']), 'excluded': len(omitted),
                      'uninspected': len(unread), 'python_parse_failures': sorted(self.parse_failures)},
            'areas': {key: sorted(paths) for key, paths in self.areas.items()},
            'frameworks': sorted(self.frameworks),
            'signals': dict(self.signals),
            'routes': self.routes,
            'calls': self.calls,
            'routes': self.routes,
            'calls': self.calls,
            'route_bodies': self.route_bodies,
            'dependencies': [
                {'from': origin, 'to': target, 'evidence': rows}
                for (origin, target), rows in sorted(self.edges.items())
            ],
            'security_review': [
                {'id': key, 'label': label, 'next_step': step,
                 'status': 'signal_present' if self.signals.get(key) else 'unknown'}
                for key, (label, step) in CONTROLS.items()
            ],
        }
        save(run / 'static-audit.json', payload)
        architecture = ['# Audit d’architecture', '', '## Périmètre observé', '',
                        f"{len(meta['inventory'])} fichiers inspectés, {len(omitted)} entrées exclues, "
                        f"{len(unread)} non inspectées et {len(self.parse_failures)} fichiers Python non analysables.", '',
                        '## Cartographie par chemin', '']
        for key, (label, _) in ARCHITECTURE.items():
            paths = sorted(self.areas.get(key, []))
            architecture.append(f"- **{label}** · {len(paths)} fichiers. "
                                + ('Exemple : ' + code_span(paths[0]) if paths else 'Présence indéterminée.'))
        architecture += ['', '## Interfaces et traitements observés', '']
        for key, label in SIGNALS.items():
            architecture += self.section(key, label)
        architecture += ['## Dépendances entre domaines', '',
                         'Imports Python absolus résolus vers des modules inspectés.', '']
        for (origin, target), rows in sorted(self.edges.items()):
            row = rows[0]
            architecture.append(f"- {ARCHITECTURE[origin][0]} → {ARCHITECTURE[target][0]} "
                                f"· {len(rows)} imports, dont {code_span(row['path'])}, lignes "
                                f"{row['start_line']}–{row['end_line']}.")
        architecture.append('')
        architecture += ['## Limites', '', 'Les regroupements par chemin sont indicatifs. '
                         'Les signaux isolés ne démontrent pas une chaîne d’appels, une topologie déployée '
                         'ou une couverture de tests. Le registre JSON contient toutes les citations.', '']
        security = ['# Audit de sécurité statique', '',
                    'Les signaux sont des points de revue. La présence et l’efficacité des contrôles '
                    'restent à établir sur les flux concernés.', '']
        for key, (label, step) in CONTROLS.items():
            security += self.section(key, label) + [step, '']
        security += ['## Contrôles à qualifier', '',
                     '- Révocation de session, droits par action, isolation des workspaces et objets.',
                     '- Validation des destinations, exposition des données, journalisation et sorties des outils IA.',
                     '- Dépendances et artefacts de livraison, sauvegarde et contrôles de déploiement.', '',
                     'Le registre JSON contient les plages et empreintes des signaux. Les validations '
                     'd’exécution et les paramètres externes restent indéterminés.', '']
        for name, lines in (('architecture-audit.md', architecture), ('security-audit.md', security)):
            (run / name).write_text('\n'.join(lines), encoding='utf-8')
        self.write_diagrams(run)

    def section(self, key, label):
        rows = self.signals.get(key, [])
        lines = [f'### {label}', '']
        if not rows:
            return lines + ['Indéterminé dans le périmètre inspecté.', '']
        lines.append(f'{len(rows)} occurrences. Exemples dans le code inspecté.')
        for row in rows[:5]:
            lines.append(f"- {code_span(row['path'])}, lignes {row['start_line']}–{row['end_line']}")
        return lines + ['']

    def write_diagrams(self, run):
        diagrams = run / 'diagrams'
        diagrams.mkdir(exist_ok=True)
        architecture = ['flowchart LR', '    Root[Inventaire source]']
        for key, (label, _) in ARCHITECTURE.items():
            if self.areas.get(key):
                architecture.append(f'    Root --> {key}["{label} · {len(self.areas[key])} fichiers"]')
        for origin, target in sorted(self.edges):
            architecture.append(f'    {origin} -. importe .-> {target}')
        workflow = ['flowchart LR', '    Root[Signaux présents dans les fonctions de route]']
        for key in ('dependency', 'async', 'persistence'):
            count = sum(key in body['signals'] for body in self.route_bodies)
            if count:
                workflow.append(f'    Root --> {key}["{SIGNALS[key]} · {count} routes"]')
        security = ['flowchart LR', '    Root[Revue de sécurité]']
        for key, (label, _) in CONTROLS.items():
            status = f'{len(self.signals[key])} signaux' if self.signals.get(key) else 'indéterminé'
            security.append(f'    Root --> {key}["{label} · {status}"]')
        for name, lines in (('architecture', architecture), ('workflow', workflow), ('security', security)):
            (diagrams / f'{name}.mmd').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def code_span(value):
    # Prevent untrusted paths from becoming Markdown or HTML.
    value = ''.join(char if char.isprintable() else '?' for char in value)
    delimiter = '`' * (max((len(run) for run in re.findall(r'`+', value)), default=0) + 1)
    return f'{delimiter} {value} {delimiter}'

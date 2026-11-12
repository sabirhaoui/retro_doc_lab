import ast
from pathlib import PurePosixPath


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


def literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def keyword(node, key, default=None):
    for arg in node.keywords:
        if arg.arg == key:
            return literal(arg.value)
    return default


def module(path):
    return path.removesuffix('.py').replace('/', '.').removesuffix('.__init__')


def analyze(model, path, text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        model.limitations.append(path + ': Python AST non analysable')
        return
    aliases = {}
    qualified_functions = {}
    def scopes(node, prefix):
        for child in ast.iter_child_nodes(node):
            nested = prefix
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                nested = prefix + '.' + child.name
                qualified_functions[id(child)] = nested
            scopes(child, nested)
    scopes(tree, module(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                parent = module(path).split('.')[:-node.level]
                base = '.'.join(parent + ([base] if base else []))
            for alias in node.names:
                aliases[alias.asname or alias.name] = base + '.' + alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name

    def qualify(name):
        first, _, rest = name.partition('.')
        return aliases.get(first, module(path) + '.' + first) + ('.' + rest if rest else '')

    constant_proofs = []

    def value(node):
        direct = literal(node)
        if direct is not None:
            return direct
        if isinstance(node, (ast.Name, ast.Attribute)):
            symbol = qualify(dotted(node))
            candidates = [(v, e) for k, (v, e) in getattr(model, 'constants', {}).items()
                          if k == symbol or k.endswith('.' + symbol)]
            if len(candidates) == 1:
                constant_proofs.extend(candidates[0][1])
                return candidates[0][0]
        if isinstance(node, ast.JoinedStr):
            parts = [value(v.value) if isinstance(v, ast.FormattedValue) else value(v) for v in node.values]
            if all(p is not None for p in parts):
                return ''.join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = value(node.left), value(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    def kw(node, name, default=None):
        return next((value(k.value) for k in node.keywords if k.arg == name), default)

    def ev(node):
        return [model.evidence(path, node.lineno, node.end_lineno)] + list(constant_proofs)

    owners = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            constructor = qualify(dotted(node.value.func))
            if constructor in {'fastapi.FastAPI', 'fastapi.APIRouter', 'fastapi.applications.FastAPI', 'fastapi.routing.APIRouter'}:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        prefix = kw(node.value, 'prefix', '')
                        obj = model.add('api_owner', module(path) + '.' + target.id, target.id, ev(node),
                                        symbol=module(path) + '.' + target.id,
                                        owner_type='app' if constructor.endswith('.FastAPI') else 'router',
                                        prefix=prefix)
                        owners[target.id] = obj
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'include_router':
            owner = owners.get(dotted(node.func.value))
            if owner and node.args:
                model.add('mount', path + ':' + str(node.lineno), 'include_router', ev(node),
                          source=owner['id'], router_symbol=qualify(dotted(node.args[0])),
                          prefix=keyword(node, 'prefix', ''))
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        function_symbol = qualified_functions[id(node)]
        function = model.add('function', function_symbol, node.name, ev(node), symbol=function_symbol)
        handlers = []
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            if isinstance(deco.func, ast.Attribute) and deco.func.attr in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'api_route'}:
                owner = owners.get(dotted(deco.func.value))
                if owner:
                    route = value(deco.args[0]) if deco.args else kw(deco, 'path')
                    methods = [deco.func.attr.upper()]
                    if deco.func.attr == 'api_route':
                        methods = []
                        for kw in deco.keywords:
                            if kw.arg == 'methods' and isinstance(kw.value, (ast.List, ast.Tuple)):
                                methods = [literal(v) for v in kw.value.elts if literal(v)]
                        methods = methods or ['UNKNOWN']
                    for method in methods:
                        handlers.append(model.add('endpoint', path + ':' + node.name + ':' + str(deco.lineno) + ':' + method,
                            node.name, ev(deco), source=owner['id'], method=method, route=route,
                            symbol=function_symbol, handler_evidence=ev(node)))
            if dotted(deco.func).endswith(('.task', '.shared_task')) or qualify(dotted(deco.func)) == 'celery.shared_task':
                model.add('task', function_symbol, node.name, ev(deco), symbol=function_symbol)
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            name = dotted(call.func)
            if name:
                model.pending_calls.append((function['id'], qualify(name), ev(call)))
            tail = name.rsplit('.', 1)[-1]
            category = ('task_publish' if tail in {'delay', 'apply_async', 'send_task'} else
                        'persistence' if tail in {'execute', 'commit', 'flush', 'query'} else
                        'dependency' if tail in {'Depends', 'Security'} else
                        'error' if tail == 'HTTPException' else 'retry' if tail == 'retry' else None)
            if category:
                obj = model.add('operation', path + ':' + str(call.lineno) + ':' + str(call.col_offset),
                                tail, ev(call), status='inféré' if category == 'persistence' else 'observé',
                                category=category, symbol=qualify(name.removesuffix('.' + tail)),
                                enclosing=function_symbol, function=function['id'])
                for handler in handlers:
                    model.add('relation', handler['id'] + obj['id'], category,
                              handler['evidence'] + obj['evidence'], source=handler['id'], target=obj['id'])

"""Resolve static mounts and retain ambiguous/dynamic HTTP candidates."""
import re


def normalize(route):
    if route is None:
        return None
    route = route.split('?', 1)[0].rstrip('/') or '/'
    route = re.sub(r'\$\{[^}]+\}|\{[^}]+\}|:[A-Za-z_]\w*', '{}', route)
    return route if route.startswith('/') else None


def compatible(call, endpoint):
    if call is None or endpoint is None:
        return False
    left, right = call.strip('/').split('/'), endpoint.strip('/').split('/')
    return len(left) == len(right) and all(a == b or b == '{}' for a, b in zip(left, right))


def resolve(model):
    functions = model.select('function')
    by_symbol = {}
    by_suffix = {}
    for function in functions:
        by_symbol.setdefault(function['symbol'], []).append(function)
        parts = function['symbol'].split('.')
        for i in range(1, len(parts)):
            by_suffix.setdefault('.'.join(parts[i:]), []).append(function)
    def find_functions(symbol):
        exact = by_symbol.get(symbol, [])
        return exact or by_suffix.get(symbol, [])
    for source, symbol, proofs in model.pending_calls:
        candidates = find_functions(symbol)
        if len(candidates) == 1 and candidates[0]['id'] != source:
            target = candidates[0]
            model.add('relation', source + target['id'], 'appel Python', proofs + target['evidence'],
                      status='inféré', source=source, target=target['id'])
    for endpoint in model.select('endpoint'):
        candidates = by_symbol.get(endpoint['symbol'], [])
        if len(candidates) == 1:
            model.add('relation', endpoint['id'] + candidates[0]['id'], 'handler', endpoint['evidence'],
                      source=endpoint['id'], target=candidates[0]['id'])
    for operation in model.select('operation'):
        model.add('relation', operation['function'] + operation['id'], operation['category'], operation['evidence'],
                  source=operation['function'], target=operation['id'])
    owners = model.select('api_owner')
    mounts = model.select('mount')

    def owner_matches(symbol):
        exact = [o for o in owners if o['symbol'] == symbol]
        return exact or [o for o in owners if o['symbol'].endswith('.' + symbol)]

    incoming = {}
    for mount in mounts:
        candidates = owner_matches(mount['router_symbol'])
        mount['candidates'] = [c['id'] for c in candidates]
        mount['status'] = 'inféré' if len(candidates) == 1 else 'non résolu'
        if len(candidates) == 1:
            incoming.setdefault(candidates[0]['id'], []).append(mount)

    def paths(owner_id, visited=()):
        if owner_id in visited:
            return []
        owner = model.items[owner_id]
        if owner['prefix'] is None:
            return []
        if owner['owner_type'] == 'app':
            return [(owner['prefix'], owner['evidence'])]
        result = []
        for mount in incoming.get(owner_id, []):
            if mount['prefix'] is None:
                continue
            for base, proofs in paths(mount['source'], visited + (owner_id,)):
                result.append((base + mount['prefix'] + owner['prefix'], proofs + mount['evidence'] + owner['evidence']))
        return result

    for endpoint in model.select('endpoint'):
        endpoint['resolved_paths'] = []
        if endpoint['route'] is not None:
            for prefix, proofs in paths(endpoint['source']):
                endpoint['resolved_paths'].append({'route': prefix + endpoint['route'], 'evidence': proofs})
        if not endpoint['resolved_paths']:
            endpoint['resolution_status'] = 'non résolu'

    for call in model.select('http_call'):
        route = normalize(call['route'])
        routes = [(route, [])] if route else []
        for rewrite in model.select('rewrite'):
            if route and route.startswith(rewrite['old']):
                routes.append((rewrite['new'] + route[len(rewrite['old']):], rewrite['evidence']))
        candidates, proofs = [], list(call['evidence'])
        for endpoint in model.select('endpoint'):
            if endpoint['method'] != call['method']:
                continue
            for resolved in endpoint['resolved_paths']:
                for candidate, rewrite_proofs in routes:
                    if compatible(candidate, normalize(resolved['route'])):
                        candidates.append(endpoint['id'])
                        proofs += endpoint['evidence'] + resolved['evidence'] + rewrite_proofs
        candidates = sorted(set(candidates))
        unique = len(candidates) == 1
        flow = model.add('flow', call['id'], call['method'] + ' parcours HTTP', proofs,
                        status='inféré' if unique else 'non résolu', source=call['id'],
                        candidates=candidates, coverage='partial' if unique else 'unknown',
                        missing=['Liaison ecran-service et valeurs runtime a confirmer'] if unique else
                                ['URL dynamique, montage, proxy ou candidat unique manquant'])
        if unique:
            flow['target'] = candidates[0]
            model.add('relation', call['id'] + candidates[0], 'HTTP', proofs,
                      status='inféré', source=call['id'], target=candidates[0])
        service_classes = [s for s in model.select('angular_service') if s['evidence'][0]['path'] == call['context']]
        screens = [u for u in model.select('ui_invocation') if u['member'] == call.get('member')
                   and any(s['symbol'] == u['service'] for s in service_classes)]
        flow['screens'] = [u['id'] for u in screens]
        for screen in screens:
            model.add('relation', screen['id'] + call['id'], 'appel service Angular', screen['evidence'] + call['evidence'],
                      status='inféré', source=screen['id'], target=call['id'])
            flow['evidence'] += screen['evidence']
    for publish in [o for o in model.select('operation') if o['category'] == 'task_publish']:
        tasks = [t for t in model.select('task') if t['symbol'] == publish['symbol'] or t['symbol'].endswith('.' + publish['symbol'])]
        proofs = publish['evidence'] + [e for t in tasks for e in t['evidence']]
        flow = model.add('async_flow', publish['id'], 'Publication de tache', proofs,
                        status='inféré' if len(tasks) == 1 else 'non résolu',
                        source=publish['id'], candidates=[t['id'] for t in tasks])
        if len(tasks) == 1:
            flow['target'] = tasks[0]['id']

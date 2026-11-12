"""Build bounded, evidence-linked Mermaid sequences from the static call graph."""
import json
import re
from pathlib import Path

from .pipeline import save


MAX_SEQUENCES = 20
MAX_DEPTH = 4
MAX_CALLS_PER_FUNCTION = 5


def safe(value):
    return re.sub(r'[^A-Za-z0-9_ ./=-]', '_', str(value))[:100]


def participant(path):
    parts = Path(path).with_suffix('').parts
    label = '.'.join(parts[-3:]) if parts else 'module'
    return 'p_' + re.sub(r'\W', '_', label), label


def generate(run):
    audit_path = run / 'static-audit.json'
    if not audit_path.is_file():
        raise ValueError('Sequence generation requires static-audit.json')
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    calls = audit.get('calls', [])
    by_caller = {}
    for call in calls:
        if call.get('target_symbol'):
            by_caller.setdefault(call['caller'], []).append(call)
    routes = sorted(
        audit.get('routes', []),
        key=lambda route: (
            -len(route.get('signals', [])),
            route['evidence']['path'],
            route['evidence']['start_line'],
        ),
    )
    selected = routes[:MAX_SEQUENCES]
    sequence_dir = run / 'diagrams' / 'sequences'
    sequence_dir.mkdir(parents=True, exist_ok=True)
    index = []

    for number, route in enumerate(selected, 1):
        interactions = []
        frontier = [(route['handler_symbol'], route['handler_path'], 0)]
        visited = set()
        while frontier and len(interactions) < 20:
            caller, caller_path, depth = frontier.pop(0)
            if caller in visited or depth >= MAX_DEPTH:
                continue
            visited.add(caller)
            outgoing = by_caller.get(caller, [])[:MAX_CALLS_PER_FUNCTION]
            for call in outgoing:
                target = call['target_symbol']
                interactions.append(call)
                frontier.append((target, call['target_path'], depth + 1))

        api_id, api_label = participant(route['handler_path'])
        participants = {api_id: api_label}
        for call in interactions:
            target_id, target_label = participant(call['target_path'])
            participants[target_id] = target_label
        lines = ['sequenceDiagram', '  participant Client']
        lines.extend(f'  participant {ident} as {safe(label)}'
                     for ident, label in sorted(participants.items()))
        lines.append(f"  Client->>{api_id}: {safe(route.get('method', 'HTTP'))} handler (observé)")
        previous_id = api_id
        for call in interactions:
            target_id, _ = participant(call['target_path'])
            lines.append(f"  {previous_id}->>{target_id}: {safe(call['callee_name'])} (inféré)")
            previous_id = target_id
        if 'dependency' in route.get('signals', []):
            lines.append(f'  Note over {api_id}: Dépendance injectée détectée (observé)')
        if 'persistence' in route.get('signals', []):
            lines.append(f'  Note over {api_id}: Opération de persistance candidate (observé)')
        if 'async' in route.get('signals', []):
            lines.append(f'  Note over {api_id}: Publication asynchrone candidate (observé)')
        if not interactions:
            lines.append('  Note over Client: Aucun appel inter-module unique résolu')
        route_evidence = route['evidence']
        filename = f'request-{number:03d}.mmd'
        diagram_text = '\n'.join(lines) + '\n'
        (sequence_dir / filename).write_text(diagram_text, encoding='utf-8')
        index.append({
            'id': f'request-{number:03d}',
            'diagram': f'diagrams/sequences/{filename}',
            'method': route.get('method'),
            'route': route.get('route'),
            'handler': route['handler_symbol'],
            'status': 'inféré' if interactions else 'observé',
            'route_evidence': route_evidence,
            'call_evidence': [call['evidence'] for call in interactions],
        })

    save(run / 'sequence-index.json', {
        'schema_version': 1,
        'status': 'partial',
        'selected_routes': len(selected),
        'total_routes': len(routes),
        'truncated': len(routes) > len(selected),
        'sequences': index,
        'limitations': [
            'Les diagrammes sont des reconstructions statiques, pas des traces d execution.',
            'La resolution des appels dynamiques, callbacks et dependances injectees est incomplete.',
            f'Au plus {MAX_SEQUENCES} routes sont detaillees; toutes restent dans static-audit.json.',
        ],
    })

    doc = ['# Séquences backend', '',
           f'{len(selected)} séquence(s) détaillée(s) sur {len(routes)} route(s) observée(s). '
           'Les appels inter-modules résolus sont marqués « inféré ».', '']
    for row in index:
        doc += [f"## {row['method']} {row['route'] or '(route dynamique)'}",
                '', f"Handler : `{row['handler']}`; preuve `{row['route_evidence']['path']}:"
                f"{row['route_evidence']['start_line']}-{row['route_evidence']['end_line']}`.",
                '', '```mermaid', diagram_text.rstrip(), '```', '',
                f"Source Mermaid : `{row['diagram']}`.", '']
    if len(routes) > len(selected):
        doc += [f"Le détail est plafonné à {MAX_SEQUENCES} séquences; les autres routes restent indexées "
                'dans `static-audit.json`.', '']
    (run / 'sequences.md').write_text('\n'.join(doc), encoding='utf-8')
    return index

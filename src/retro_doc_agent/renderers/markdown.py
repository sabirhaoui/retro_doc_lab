import re
from ..model import dump


def safe(text):
    return re.sub(r'[^A-Za-z0-9_ ./=-]', '_', str(text))[:120]


def cite(item):
    return ', '.join(sorted({f"`{e['path']}:{e['start_line']}-{e['end_line']}`" for e in item['evidence']}))


def render(model, output, manifest):
    diagrams = output / 'diagrams'
    diagrams.mkdir()
    dump(output / 'architecture.json', model.export())
    dump(output / 'inventory.json', manifest)
    dump(output / 'coverage.json', {'schema_version': 2,
        'items': [{'id': f['id'], 'status': f['coverage'], 'evidence': f['evidence'],
                   'documentation': ['sequences.md']} for f in model.select('flow')],
        'excluded_files': manifest['excluded'], 'uninspected_files': manifest['unreadable'],
        'baseline': 'unknown; documentation existante non comparee'})
    sections = {
        'global': ('Architecture globale', {'technology', 'api_owner', 'compose_service', 'proxy_rule'}),
        'detail': ('Architecture detaillee', {'endpoint', 'angular_component', 'angular_service', 'ui_route', 'operation', 'task', 'mount'}),
        'states': ('Etats internes', {'state', 'transition'}),
    }
    for name, (title, kinds) in sections.items():
        rows = [x for x in model.items.values() if x['kind'] in kinds]
        lines = ['# ' + title, '', 'Les identifiants renvoient au modele JSON. Portee statique partielle.', '']
        for row in rows:
            lines += [f"- `{row['id']}` **{safe(row['label'])}** ({row['status']}) — {cite(row)}"]
        if not rows:
            lines += ['Aucun element etabli dans la portee inspectee.']
        if name == 'states':
            lines += ['', 'Domaines metier et taches : non etablis par cet analyseur. Les affectations UI',
                      'ne prouvent pas un ordre entre etats; les origines des transitions restent inconnues.']
        (output / (name + '.md')).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    global_nodes = model.select('technology') + model.select('compose_service') + model.select('api_owner')
    # Group duplicate technologies, retaining every proof in the JSON and global index.
    seen = set()
    graph = ['flowchart LR']
    for row in global_nodes:
        if row['label'] in seen:
            continue
        seen.add(row['label'])
        graph.append(f"  {row['id']}[\"{safe(row['label'])}\"]")
    if len(graph) == 1:
        for row in model.select('component')[:30]:
            graph.append(f"  {row['id']}[\"{safe(row['label'])}\"]")
    if len(graph) == 1:
        graph.append('  unknown["Aucun composant etabli"]')
    (diagrams / 'architecture.mmd').write_text('\n'.join(graph) + '\n', encoding='utf-8')
    detail = ['flowchart LR']
    relations = model.select('relation')
    # Keep the diagram usable; the exhaustive graph is in architecture.json.
    diagram_relations = relations[:250]
    nodes = sorted({r[k] for r in diagram_relations for k in ('source', 'target')})
    for ident in nodes:
        detail.append(f'  {ident}["{safe(model.items[ident]["label"])}"]')
    for row in diagram_relations:
        arrow = '-.->' if row['status'] == 'inféré' else '-->'
        detail.append(f"  {row['source']} {arrow}|{safe(row['label'])}| {row['target']}")
    if not relations:
        detail.append('  unknown["Relations non etablies"]')
    (diagrams / 'detail.mmd').write_text('\n'.join(detail) + '\n', encoding='utf-8')
    index = ['# Parcours et couverture', '', 'Rapprochements statiques inferes; aucune execution du projet.', '',
             'La liaison entre ecran et service Angular reste non resolue sauf preuve complementaire.', '']
    seen = set()
    selected = []
    for flow in model.select('flow'):
        call = model.items[flow['source']]
        index.append(f"- `{flow['id']}` {call['method']} ({flow['status']}, {len(flow['candidates'])} candidat(s)) : {cite(flow)}")
        signature = (call['method'], call['route'], flow.get('target'))
        if 'target' in flow and signature not in seen:
            seen.add(signature)
            selected.append(flow)
    # One representative sync and one proven candidate asynchronous path; remaining paths stay indexed.
    selected.sort(key=lambda f: (not bool(f.get('screens')), f['id']))
    for flow in selected[:1]:
        endpoint = model.items[flow['target']]
        sequence = ['sequenceDiagram', '  participant UI as Appel Angular', '  participant API as Handler FastAPI',
                    '  Note over UI,API: Rapprochement infere - ' + flow['id'],
                    '  UI->>API: ' + safe(model.items[flow['source']]['method'] + ' ' + endpoint['label'])]
        if flow.get('screens'):
            screen = model.items[flow['screens'][0]]
            sequence[1:1] = ['  participant E as Composant Angular']
            sequence.insert(-1, '  E->>UI: ' + safe(screen['member']) + ' - lien infere')
        operations = [model.items[r['target']] for r in relations if r['source'] == endpoint['id']]
        for operation in operations:
            if 'category' in operation:
                sequence.append('  Note over API: ' + safe(operation['category']) + ' - ' + operation['id'])
        frontier, visited = [(endpoint['id'], 'API', 0)], set()
        while frontier:
            source, participant, depth = frontier.pop(0)
            if source in visited or depth > 3:
                continue
            visited.add(source)
            children = [r for r in relations if r['source'] == source and r['label'] in {'handler', 'appel Python'}]
            for relation in children[:5]:
                target = model.items[relation['target']]
                if relation['label'] == 'handler':
                    frontier.append((target['id'], participant, depth))
                    continue
                sequence += ['  participant ' + target['id'] + ' as ' + safe(target['label']),
                             '  ' + participant + '->>' + target['id'] + ': appel infere']
                frontier.append((target['id'], target['id'], depth + 1))
        (diagrams / 'workflow.mmd').write_text('\n'.join(sequence) + '\n', encoding='utf-8')
        index += ['', 'Parcours synchrone representatif : `diagrams/workflow.mmd`, ' + cite(flow)]
    if not selected:
        (diagrams / 'workflow.mmd').write_text('sequenceDiagram\n  participant U as Inconnu\n  Note over U: Aucun parcours HTTP resolu\n', encoding='utf-8')
    async_flows = model.select('async_flow')
    for flow in async_flows:
        index.append(f"- Asynchrone `{flow['id']}` ({flow['status']}) : {cite(flow)}")
    resolved_async = [f for f in async_flows if 'target' in f]
    if resolved_async:
        flow = resolved_async[0]
        (diagrams / 'async.mmd').write_text('sequenceDiagram\n  participant P as Publication\n  participant T as Tache Celery\n'
            '  Note over P,T: Liaison inferee - ' + flow['id'] + '\n  P->>T: Soumission statique\n', encoding='utf-8')
    else:
        index += ['', 'Aucun lien publication-execution de tache etabli.']
    (output / 'sequences.md').write_text('\n'.join(index) + '\n', encoding='utf-8')
    states = ['stateDiagram-v2']
    for row in model.select('state'):
        states.append(f'  state "{safe(row["label"])}" as {row["id"]}')
    transitions = model.select('transition')
    if transitions:
        states.append('  state "Origine non resolue" as origin_unknown')
        for row in transitions:
            states.append(f"  origin_unknown --> {row['target']}: {safe(row['event'])} infere")
    # Deliberately no invented transitions from an assumed initial state.
    if len(states) == 1:
        states.append('  state "Etats non etablis" as unknown')
    (diagrams / 'states.mmd').write_text('\n'.join(states) + '\n', encoding='utf-8')
    dump(output / 'validation.json', {'model_references': 'passed', 'mermaid': {
        'status': 'unvalidated', 'parser': None, 'reason': 'Parseur local non configure; verification de structure seulement'}})
    overview = ['# Retrodocumentation statique', '',
        '[Architecture globale](global.md) · [Architecture detaillee](detail.md) · [Sequences](sequences.md) · [Etats internes](states.md)', '',
        f"Fichiers inspectes : {len(manifest['files'])}; exclusions : {len(manifest['excluded'])}; non inspectes : {len(manifest['unreadable'])}.",
        '', 'Revision et etat Git : inconnus. Empreintes dans inventory.json. Aucun code cible execute.',
        'Acteurs humains, deploiement effectif et couverture semantique complete : non etablis.',
        '', 'Diagramme detail limite aux 250 premieres relations; graphe complet dans architecture.json.',
        '', '## Limites', ''] + ['- ' + x for x in sorted(set(model.limitations))]
    (output / 'index.md').write_text('\n'.join(overview) + '\n', encoding='utf-8')

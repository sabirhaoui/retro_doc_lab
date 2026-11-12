"""Generate a PlantUML component diagram from a local retrospective audit."""

import argparse
import json
from pathlib import Path
import re
import sys

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / 'src'))

from retro_doc_agent.pipeline import configuration, linked
from retro_doc_agent.static_audit import ARCHITECTURE


def generate(config, run_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', run_id):
        raise ValueError('Invalid run ID')
    _, source, output = configuration(config)
    run = output / run_id
    audit_path = run / 'static-audit.json'
    manifest_path = run / 'run.json'
    diagrams = run / 'diagrams'
    if any(linked(path) for path in (audit_path, manifest_path, diagrams, run, output, *output.parents)):
        raise ValueError('Linked audit paths are not supported')

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    if (manifest.get('source_root') != str(source) or audit.get('schema_version') != 1
            or manifest.get('status') not in {'partial', 'completed'}
            or manifest.get('stages', {}).get('inventory') != 'completed'):
        raise ValueError('Expected a completed local inventory and its static audit')

    inventory = {entry['path']: entry for entry in manifest['inventory']}
    areas = {key for key, paths in audit['areas'].items() if paths and key in ARCHITECTURE}
    lines = [
        '@startuml', 'title Architecture observée — dépendances statiques',
        'left to right direction', 'skinparam componentStyle uml2',
    ]
    for key, (label, _) in ARCHITECTURE.items():
        if key in areas:
            lines.append(f'component "{label}" as {key}')

    for index, edge in enumerate(audit['dependencies']):
        origin, target, evidence = edge['from'], edge['to'], edge['evidence']
        if origin not in areas or target not in areas or not evidence:
            raise ValueError('Invalid dependency in static audit')
        for citation in evidence:
            entry = inventory.get(citation['path'])
            if (not entry or entry['sha256'] != citation['sha256']
                    or not 1 <= citation['start_line'] <= citation['end_line'] <= entry['lines']
                    or citation['target_path'] not in inventory):
                raise ValueError('Invalid dependency citation')
        lines.append(f'{origin} ..> {target} : imports Python ({len(evidence)}) [D{index}]')

    lines += [
        'legend bottom',
        '  Les composants regroupent les fichiers par domaine.',
        '  Dn renvoie à dependencies[n] dans static-audit.json, à partir de 0.',
        '  Les appels en exécution et la topologie déployée restent indéterminés.',
        'endlegend', '@enduml', '',
    ]
    destination = diagrams / 'architecture.puml'
    diagram = '\n'.join(lines)
    try:
        with destination.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(diagram)
    except FileExistsError:
        if linked(destination) or destination.read_text(encoding='utf-8') != diagram:
            raise ValueError('Existing architecture.puml differs; use a new run')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=LAB / 'config' / 'agent.json')
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    try:
        print(generate(args.config, args.run_id))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()

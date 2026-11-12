"""Assemble the phase outputs into a concise, evidence-linked audit report."""
import json


def render(run):
    characterization = json.loads((run / 'characterization.json').read_text(encoding='utf-8'))
    audit = json.loads((run / 'static-audit.json').read_text(encoding='utf-8'))
    sequence_index = json.loads((run / 'sequence-index.json').read_text(encoding='utf-8'))
    inventory = characterization['inventory']
    resolved_calls = sum(bool(call.get('target_symbol')) for call in audit.get('calls', []))
    lines = [
        '# Audit de rétro-documentation',
        '',
        f"Source : `{audit.get('source_root') or 'révision distante'}`. Révision : "
        f"`{audit.get('source_revision') or 'inconnue'}`.",
        '',
        'Analyse statique en lecture seule. Les éléments observés et les liens inférés ne démontrent '
        'pas le comportement runtime ni la couverture documentaire.',
        '',
        '## Caractérisation',
        '',
        f"- {inventory['admitted_files']} fichiers admis; {inventory['admitted_bytes']:,} octets.",
        f"- {inventory['excluded_entries']} exclusions et {inventory['uninspected_entries']} éléments non inspectés.",
        f"- Python : {inventory['python_files']} fichiers / {inventory['python_lines']:,} lignes; "
        f"{inventory['classes']} classes et {inventory['functions']} fonctions déclarées.",
        f"- Frameworks observés dans les imports : {', '.join(characterization['frameworks_observed']) or 'aucun établi'}.",
        f"- Points d’entrée candidats : {len(characterization['entrypoints'])}; configurations candidates : "
        f"{len(characterization['configuration_candidates'])}.",
        '',
        '## Architecture et interfaces',
        '',
        f"- {len(audit.get('routes', []))} déclarations de route et "
        f"{len(audit.get('dependencies', []))} liens entre domaines observés.",
        f"- {len(audit.get('calls', []))} appels analysés, dont {resolved_calls} cibles locales résolues; "
        'ces liens restent des inférences statiques.',
        '',
        '### Modularité et couplage',
        '',
        f"- {len(audit.get('areas', {}))} domaines de chemins classés; les comptes par domaine sont disponibles dans `static-audit.json`.",
        f"- {len(audit.get('dependencies', []))} paires de domaines et "
        f"{sum(len(edge['evidence']) for edge in audit.get('dependencies', []))} imports inter-domaines résolus.",
        '- Les regroupements par chemin donnent une indication de modularité; la cohésion métier et les dépendances runtime restent inconnues.',
        '',
        '### Imports entre domaines',
        '',
    ]
    for edge in audit.get('dependencies', []):
        lines.append(f"- `{edge['from']}` → `{edge['to']}` : {len(edge['evidence'])} import(s) résolu(s).")
    if not audit.get('dependencies'):
        lines.append('Aucun import inter-domaines résolu dans le périmètre admis.')
    lines += [
        '',
        '- [Audit d’architecture](architecture-audit.md)',
        '- [Observations de sécurité à qualifier](security-audit.md)',
        '',
        '## Séquences représentatives',
        '',
        f"{sequence_index['selected_routes']} séquences générées sur {sequence_index['total_routes']} routes observées.",
        '- [Index des séquences](sequences.md)',
        '',
    ]
    for item in sequence_index.get('sequences', []):
        diagram = (run / item['diagram']).read_text(encoding='utf-8').rstrip()
        lines += [f"### {item['method']} — {item['handler']}", '',
                  '```mermaid', diagram, '```', '']
    lines += [
        '## Limites',
        '',
        '- Exclusions et limites d’inventaire réduisent le périmètre analysé.',
        '- Aucune commande, suite de tests ou module du dépôt source n’a été exécuté.',
        '- Les configurations effectives, les déploiements, les parcours indirects et les états métier restent à confirmer.',
        '- La syntaxe Mermaid est marquée non validée sans parseur dédié.',
        '',
    ]
    (run / 'audit_report.md').write_text('\n'.join(lines), encoding='utf-8')

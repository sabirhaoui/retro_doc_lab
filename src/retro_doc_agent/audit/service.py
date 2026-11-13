"""Analyse des dépendances Python et génération des livrables d'audit."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retro_doc_agent import __version__
from retro_doc_agent.analyzers.python import PythonAnalyzer
from retro_doc_agent.config import ToolConfig
from retro_doc_agent.models.architecture import (
    ArchitectureAudit,
    Finding,
    ImportEdge,
    ModuleFact,
    PythonAnalysis,
)
from retro_doc_agent.models.characterization import Fact
from retro_doc_agent.models.report import EvidenceRef, RunManifest
from retro_doc_agent.scanner import ScanResult, scan_source
from retro_doc_agent.scanner.filesystem import FileRecord, ScannedText

DOC_PATH_PATTERN = re.compile(r"[A-Za-z0-9_.\\/-]+\.py\b")
TEST_PARTS = {"test", "tests", "__tests__"}
CI_NAMES = {"azure-pipelines.yml", "bitbucket-pipelines.yml", ".gitlab-ci.yml"}
SEVERITY_ORDER = {"critique": 0, "majeur": 1, "mineur": 2}


def run(static_audit: Any, run_directory: Path, meta: dict[str, Any], omitted: list[str], unread: list[str]) -> None:
    """Compatibilité avec le pipeline historique : produit les livrables d'audit statique."""
    static_audit.write(run_directory, meta, omitted, unread)


def audit(source_root: Path, output_root: Path, config: ToolConfig) -> Path:
    """Génère les livrables d'audit sans exécuter le dépôt source."""
    started_at = datetime.now(UTC)
    source = source_root.expanduser().resolve(strict=True)
    output = output_root.expanduser().resolve()
    if output == source or source in output.parents:
        raise ValueError("Le répertoire de sortie ne peut pas être situé dans la source.")

    analyzer = PythonAnalyzer()
    documentation_mentions: dict[str, list[EvidenceRef]] = defaultdict(list)

    def observe(text_file: ScannedText) -> None:
        analyzer.observe(text_file)
        if not _is_document_file(text_file.record.path):
            return
        for line_number, line in enumerate(text_file.text.splitlines(), start=1):
            for match in DOC_PATH_PATTERN.finditer(line):
                mentioned = match.group(0).replace("\\", "/").removeprefix("./")
                documentation_mentions[mentioned].append(
                    _evidence(text_file.record, line_number)
                )

    scan = scan_source(
        source,
        exclusions=config.exclude,
        max_file_bytes=config.max_file_bytes,
        on_text_file=observe,
    )
    python_analysis = analyzer.result()
    report = _build_audit(scan, python_analysis, documentation_mentions)
    run_directory = _create_run_directory(output, started_at, scan.source_hash)
    audit_directory = run_directory / "architecture-audit"
    audit_directory.mkdir()
    _write_json(audit_directory / "audit.json", report.model_dump(mode="json"))
    _write_architecture_map(audit_directory / "01-cartographie.md", report)
    _write_documentation_comparison(audit_directory / "02-architecture-reelle-vs-doc.md", report)
    _write_findings(audit_directory / "03-findings.md", report)
    _write_target_architecture(audit_directory / "04-architecture-cible.md", report)
    _write_roadmap(audit_directory / "05-roadmap.md", report)
    _write_final_report(run_directory / "FINAL-REPORT.md", report)

    finished_at = datetime.now(UTC)
    limitations = list(report.limitations)
    limitations.append("[NON VÉRIFIÉ] Révision Git non collectée.")
    manifest = RunManifest(
        tool_version=__version__,
        run_id=run_directory.name,
        source_root=str(scan.source_root),
        source_hash=scan.source_hash,
        started_at=started_at,
        finished_at=finished_at,
        options={
            "max_file_bytes": config.max_file_bytes,
            "no_llm": True,
            "output_root": str(output),
        },
        duration_seconds=max(0.0, (finished_at - started_at).total_seconds()),
        status="partial" if scan.uninspected_files or report.limitations else "completed",
        limitations=tuple(limitations),
    )
    _write_json(run_directory / "run-manifest.json", manifest.model_dump(mode="json"))
    _write_json(
        run_directory / "run.json",
        {
            "schema_version": 1,
            "status": manifest.status,
            "source_root": str(scan.source_root),
            "source_revision": None,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "inspected_files": [item.path for item in scan.files],
            "errors": [],
            "limitations": limitations,
        },
    )
    (run_directory / "REPORT.md").write_text(
        "# Audit d'architecture\n\n"
        "Cette exécution contient l'audit statique Python.\n\n"
        "- [Rapport final](FINAL-REPORT.md)\n"
        "- [Cartographie](architecture-audit/01-cartographie.md)\n"
        "- [Findings](architecture-audit/03-findings.md)\n",
        encoding="utf-8",
    )
    return run_directory


def _build_audit(
    scan: ScanResult,
    analysis: PythonAnalysis,
    documentation_mentions: dict[str, list[EvidenceRef]],
) -> ArchitectureAudit:
    documented: list[Fact] = []
    undocumented: list[Fact] = []
    docs_files = tuple(
        item.path for item in scan.files if _is_document_file(item.path)
    )
    mention_index = {
        _normalize_reference(path): tuple(sorted(refs, key=lambda ref: (ref.path, ref.start_line)))
        for path, refs in documentation_mentions.items()
    }
    for module in analysis.modules:
        document_evidence = mention_index.get(_normalize_reference(module.path), ())
        if _normalize_reference(module.path) in mention_index:
            documented.append(
                Fact(
                    name=module.path,
                    category="référence textuelle documentation/code",
                    certainty="inférence",
                    detail="Un document mentionne textuellement le chemin du module.",
                    evidence=module.evidence + document_evidence,
                )
            )
        else:
            undocumented.append(
                Fact(
                    name=module.path,
                    category="couverture documentaire",
                    certainty="inférence",
                    detail="Aucune référence de chemin trouvée par recherche textuelle.",
                    evidence=module.evidence,
                )
            )

    cycles = _find_cycles(analysis.modules, analysis.imports)
    findings = _build_findings(scan, analysis, cycles)
    limitations = list(scan.limitations)
    limitations.extend(analysis.limitations)
    if analysis.unparsed_files:
        limitations.append(
            "[NON VÉRIFIÉ] Syntaxe Python non analysée : "
            + ", ".join(analysis.unparsed_files)
        )
    limitations.append(
        "[NON VÉRIFIÉ] Les références textuelles en documentation ne constituent "
        "pas une comparaison sémantique du comportement."
    )
    if not docs_files:
        limitations.append("[NON VÉRIFIÉ] Aucun document existant détecté dans le périmètre.")
    if len(analysis.modules) > 100 or len(analysis.imports) > 250:
        limitations.append("Le diagramme de cartographie est limité à 100 modules et 250 liens.")
    return ArchitectureAudit(
        source_hash=scan.source_hash,
        modules=analysis.modules,
        imports=analysis.imports,
        functions=analysis.functions,
        calls=analysis.calls,
        cycles=cycles,
        findings=findings,
        documentation_files=docs_files,
        documented_modules=tuple(sorted(documented, key=lambda item: item.name)),
        undocumented_modules=tuple(sorted(undocumented, key=lambda item: item.name)),
        limitations=tuple(sorted(set(limitations))),
    )


def _build_findings(
    scan: ScanResult,
    analysis: PythonAnalysis,
    cycles: tuple[tuple[str, ...], ...],
) -> tuple[Finding, ...]:
    candidates: list[tuple[str, str, str, str, tuple[EvidenceRef, ...]]] = []
    for cycle in cycles:
        members = set(cycle)
        evidence = tuple(
            edge.evidence
            for edge in analysis.imports
            if edge.source in members and edge.target in members
        )
        candidates.append(
            (
                "majeur",
                "cycles de dépendances",
                f"Cycle d'imports entre {', '.join(cycle)}",
                "Un cycle complique l'évolution indépendante des modules et augmente "
                "le risque de régressions.",
                evidence,
            )
        )

    fan_in: dict[str, int] = defaultdict(int)
    fan_out: dict[str, int] = defaultdict(int)
    for edge in analysis.imports:
        fan_out[edge.source] += 1
        fan_in[edge.target] += 1
    for module in analysis.modules:
        incoming = fan_in[module.path]
        outgoing = fan_out[module.path]
        if incoming >= 5 or outgoing >= 5:
            evidence = tuple(
                edge.evidence
                for edge in analysis.imports
                if edge.source == module.path or edge.target == module.path
            )
            candidates.append(
                (
                    "mineur",
                    "couplage",
                    f"Module à fort degré de dépendance : {module.path} "
                    f"(fan-in {incoming}, fan-out {outgoing})",
                    "Les changements de ce module peuvent toucher de nombreux composants.",
                    evidence,
                )
            )

    for module in analysis.modules:
        if module.line_count > 500 and module.evidence:
            candidates.append(
                (
                    "mineur",
                    "dette",
                    f"Fichier Python volumineux : {module.path} ({module.line_count} lignes)",
                    "Un fichier long peut concentrer plusieurs responsabilités et "
                    "augmenter le coût de maintenance.",
                    module.evidence,
                )
            )
    for function in analysis.functions:
        length = function.end_line - function.start_line + 1
        if length > 100:
            candidates.append(
                (
                    "mineur",
                    "dette",
                    f"Fonction longue : {function.name} ({length} lignes)",
                    "Une fonction longue est plus difficile à tester et à modifier localement.",
                    (function.evidence,),
                )
            )
        if function.complexity >= 15:
            candidates.append(
                (
                    "majeur",
                    "testabilité",
                    f"Complexité de contrôle élevée : {function.name} "
                    f"(score {function.complexity})",
                    "Le grand nombre de branches rend les scénarios d'exécution "
                    "difficiles à couvrir.",
                    (function.evidence,),
                )
            )
    for signal in analysis.secret_signals:
        candidates.append(
            (
                "majeur",
                "sécurité",
                "Valeur constante potentiellement sensible (valeur masquée)",
                "Si cette chaîne est un identifiant actif, elle peut être exposée dans le dépôt.",
                (signal.evidence,),
            )
        )

    scope_evidence = _scope_evidence(scan)
    if not any(_is_test_file(item.path) for item in scan.files):
        if scope_evidence:
            candidates.append(
                (
                    "mineur",
                    "testabilité",
                    "Aucun fichier de test candidat dans le périmètre inspecté",
                    "La couverture des comportements ne peut pas être établie par cet inventaire.",
                    scope_evidence,
                )
            )
    if not any(_is_ci_file(item.path) for item in scan.files):
        if scope_evidence:
            candidates.append(
                (
                    "mineur",
                    "déploiement",
                    "Aucun fichier CI/CD reconnu dans le périmètre inspecté",
                    "Les contrôles automatisés de livraison ne sont pas établis "
                    "par les fichiers inclus.",
                    scope_evidence,
                )
            )

    ordered = sorted(
        candidates,
        key=lambda item: (
            SEVERITY_ORDER[item[0]],
            item[1],
            item[2],
            tuple((proof.path, proof.start_line) for proof in item[4]),
        ),
    )
    return tuple(
        Finding(
            id=f"F-{index:03d}",
            severity=severity,  # type: ignore[arg-type]
            category=category,  # type: ignore[arg-type]
            title=title,
            impact=impact,
            recommendation=_recommendation(category),
            evidence=evidence,
        )
        for index, (severity, category, title, impact, evidence) in enumerate(ordered, start=1)
        if evidence
    )


def _find_cycles(
    modules: tuple[ModuleFact, ...], imports: tuple[ImportEdge, ...]
) -> tuple[tuple[str, ...], ...]:
    nodes = {module.path for module in modules}
    graph: dict[str, set[str]] = {node: set() for node in nodes}
    reverse: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in imports:
        graph[edge.source].add(edge.target)
        reverse[edge.target].add(edge.source)

    visited: set[str] = set()
    finished: list[str] = []
    for start in sorted(nodes):
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                finished.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            stack.extend((child, False) for child in sorted(graph[node], reverse=True))

    assigned: set[str] = set()
    components: list[tuple[str, ...]] = []
    for start in reversed(finished):
        if start in assigned:
            continue
        component: list[str] = []
        component_stack: list[str] = [start]
        assigned.add(start)
        while component_stack:
            node = component_stack.pop()
            component.append(node)
            for child in sorted(reverse[node], reverse=True):
                if child not in assigned:
                    assigned.add(child)
                    component_stack.append(child)
        if len(component) > 1 or start in graph[start]:
            components.append(tuple(sorted(component)))
    return tuple(sorted(components))


def _scope_evidence(scan: ScanResult) -> tuple[EvidenceRef, ...]:
    evidence = []
    for file in scan.files:
        if file.line_count:
            evidence.append(
                EvidenceRef(
                    path=file.path,
                    start_line=1,
                    end_line=1,
                    sha256=file.sha256,
                )
            )
        if len(evidence) >= 20:
            break
    return tuple(evidence)


def _recommendation(category: str) -> str:
    recommendations = {
        "cycles de dépendances": (
            "Introduire une frontière stable et inverser une dépendance du cycle."
        ),
        "couplage": (
            "Découper le module ou extraire une interface possédée par la couche métier."
        ),
        "dette": "Extraire des unités cohérentes et maintenir des tests de caractérisation.",
        "sécurité": (
            "Vérifier la chaîne sans l'afficher ; remplacer tout secret actif par une "
            "référence à un coffre."
        ),
        "testabilité": (
            "Ajouter des tests ciblés aux frontières et réduire les branches par fonction."
        ),
        "déploiement": "Définir un pipeline versionné avec des contrôles reproductibles.",
    }
    default = (
        "Documenter et vérifier la frontière concernée avant refactorisation."
    )
    return recommendations.get(category, default)


def _write_architecture_map(path: Path, report: ArchitectureAudit) -> None:
    nodes = report.modules[:100]
    included = {module.path for module in nodes}
    lines = [
        "# 01 — Cartographie",
        "",
        "## Modules Python observés",
        "",
    ]
    for module in nodes:
        evidence = _format_evidence(module.evidence)
        lines.append(
            f"- `{module.name}` (`{module.path}`) — responsabilité non inférée automatiquement. "
            f"Preuve : {evidence or '[NON VÉRIFIÉ]'}"
        )
    lines.extend(["", "## Graphe des imports", "", "```mermaid", "flowchart LR"])
    for module in nodes:
        node_id = _node_id(module.path)
        label = f"{module.name} ({module.path})".replace('"', "'")
        lines.append(f'  {node_id}["{label}"]')
    for edge in report.imports[:250]:
        if edge.source in included and edge.target in included:
            label = f"{edge.evidence.path}:{edge.evidence.start_line}"
            lines.append(
                f"  {_node_id(edge.source)} -->|{label}| {_node_id(edge.target)}"
            )
    lines.extend(["```", "", "## Graphe des appels résolus", ""])
    resolved_calls = [call for call in report.calls if call.target is not None]
    if resolved_calls:
        lines.extend(["```mermaid", "flowchart LR"])
        for call in resolved_calls[:250]:
            caller = call.caller.replace(".", "_")
            callee = (call.target or "").replace(".", "_")
            label = f"{call.evidence.path}:{call.evidence.start_line}"
            lines.append(f'  "{caller}" -->|{label}| "{callee}"')
        lines.append("```")
    else:
        lines.append("[NON VÉRIFIÉ] Aucun appel inter-fonction résolu statiquement.")
    lines.extend(["", "## Cycles", ""])
    if report.cycles:
        lines.extend(
            f"- {' → '.join(f'`{item}`' for item in cycle)} → `{cycle[0]}`"
            for cycle in report.cycles
        )
    else:
        lines.append(
            "Aucun cycle d'import interne n'a été détecté dans les modules Python "
            "analysés."
        )
    lines.extend(["", "## Limites", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_documentation_comparison(path: Path, report: ArchitectureAudit) -> None:
    lines = [
        "# 02 — Architecture réelle vs documentation",
        "",
        "Cette comparaison est textuelle : elle ne prouve pas qu'une description "
        "documentaire corresponde au comportement exécuté.",
        "",
        "## Documentation inspectée",
        "",
    ]
    if report.documentation_files:
        lines.extend(f"- `{item}`" for item in report.documentation_files)
    else:
        lines.append("[NON VÉRIFIÉ] Aucun document reconnu dans le périmètre.")
    lines.extend(["", "## Modules Python référencés textuellement", ""])
    lines.extend(
    f"- `{fact.name}` ({fact.certainty}) : {_format_evidence(fact.evidence)}"
    for fact in report.documented_modules
    )
    lines.extend(
    f"- `{fact.name}` ({fact.certainty}) : {fact.detail} — "
    f"{_format_evidence(fact.evidence) or '[NON VÉRIFIÉ]'}"
    for fact in report.undocumented_modules
    )
    lines.extend(
        [
            "",
            "## Limite de comparaison",
            "",
            "[NON VÉRIFIÉ] Les déclarations de comportement, routes, déploiement "
            "et architecture décrites en prose n'ont pas été comparées sémantiquement.",
            "",
            "Les chemins trouvés constituent des indices textuels ; ils ne valent pas "
            "validation de fraîcheur documentaire.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_findings(path: Path, report: ArchitectureAudit) -> None:
    lines = [
        "# 03 — Findings",
        "",
        "| ID | Sévérité | Catégorie | Constat | Preuves |",
        "|---|---|---|---|---|",
    ]
    if not report.findings:
        lines.append("| — | — | — | Aucun finding statique étayé détecté. | — |")
    for finding in report.findings:
        evidence = _format_evidence(finding.evidence)
        lines.append(
            f"| {finding.id} | {finding.severity} | {finding.category} "
            f"| {finding.title} | {evidence} |"
        )
    for finding in report.findings:
        lines.extend(
            [
                "",
                f"## {finding.id} — {finding.title}",
                "",
                f"- **Impact :** {finding.impact}",
                f"- **Recommandation :** {finding.recommendation}",
                f"- **Preuves :** {_format_evidence(finding.evidence)}",
            ]
        )
    lines.extend(["", "## Limites", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_target_architecture(path: Path, report: ArchitectureAudit) -> None:
    lines = [
        "# 04 — Architecture cible incrémentale",
        "",
        "Les propositions ci-dessous sont des recommandations, pas une description "
        "d'un système déjà déployé.",
        "",
        "1. **Stabiliser les frontières des modules.** Traiter en priorité les cycles "
        "et dépendances à fort degré détectés.",
        "2. **Isoler les effets de bord.** Garder accès aux données, services externes "
        "et configuration derrière des interfaces testables.",
        "3. **Rendre les parcours vérifiables.** Ajouter tests et instrumentation aux "
        "points d'entrée réellement confirmés.",
        "",
        "## Fondement",
        "",
    ]
    if report.findings:
        lines.extend(
            f"- `{finding.id}` ({finding.category}) : {_format_evidence(finding.evidence)}"
            for finding in report.findings
        )
    else:
        lines.append(
            "[NON VÉRIFIÉ] Aucune faiblesse structurelle statique étayée n'a été "
            "détectée ; les propositions restent génériques."
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_roadmap(path: Path, report: ArchitectureAudit) -> None:
    lines = [
        "# 05 — Roadmap",
        "",
        "| Priorité | Action | Effort | Valeur | Référence |",
        "|---|---|---|---|---|",
    ]
    if report.findings:
        for finding in report.findings:
            effort, value = _effort_value(finding.severity)
            lines.append(
                f"| {finding.severity} | {finding.recommendation} | {effort} | {value} "
                f"| {finding.id} — {_format_evidence(finding.evidence)} |"
            )
    else:
        lines.append(
            "| À qualifier | Compléter l'analyse dynamique et la revue documentaire | "
            "Moyen | Moyen | [NON VÉRIFIÉ] |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_final_report(path: Path, report: ArchitectureAudit) -> None:
    major = sum(finding.severity in {"critique", "majeur"} for finding in report.findings)
    lines = [
        "# Rapport final — audit d'architecture",
        "",
        "## Synthèse exécutive",
        "",
        f"L'analyse statique a inspecté {len(report.modules)} module(s) Python, "
        f"{len(report.imports)} lien(s) d'import interne et {len(report.functions)} "
        f"fonction(s). Elle a relevé {len(report.cycles)} cycle(s) d'import et "
        f"{len(report.findings)} finding(s), dont {major} critique(s)/majeur(s).",
        "",
        "Ces nombres décrivent le périmètre effectivement inclus ; ils ne prouvent "
        "pas le comportement à l'exécution.",
        "",
        "## Priorités",
        "",
    ]
    if report.findings:
        lines.extend(
            f"- **{finding.id} — {finding.severity} : {finding.title}.** "
            f"{finding.recommendation} Preuve : {_format_evidence(finding.evidence)}"
            for finding in report.findings[:10]
        )
    else:
        lines.append("Aucun finding statique étayé détecté.")
    lines.extend(["", "## Inconnues et limites", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    lines.extend(
        [
            "",
            "## Livrables",
            "",
            "- [Cartographie](architecture-audit/01-cartographie.md)",
            "- [Comparaison avec la documentation]"
            "(architecture-audit/02-architecture-reelle-vs-doc.md)",
            "- [Findings](architecture-audit/03-findings.md)",
            "- [Architecture cible](architecture-audit/04-architecture-cible.md)",
            "- [Roadmap](architecture-audit/05-roadmap.md)",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _is_document_file(path: str) -> bool:
    return Path(path).suffix.casefold() in {".adoc", ".md", ".rst"}


def _is_test_file(path: str) -> bool:
    normalized = path.casefold()
    name = Path(normalized).name
    return (
        any(part in TEST_PARTS for part in Path(normalized).parts)
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _is_ci_file(path: str) -> bool:
    normalized = path.casefold()
    return (
        Path(normalized).name in CI_NAMES
        or normalized.startswith(".github/workflows/")
    )


def _normalize_reference(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").casefold()


def _node_id(path: str) -> str:
    return "M_" + re.sub(r"[^A-Za-z0-9_]", "_", path)


def _format_evidence(evidence: tuple[EvidenceRef, ...]) -> str:
    return ", ".join(
        f"`{item.path}:{item.start_line}-{item.end_line}`" for item in evidence
    )


def _effort_value(severity: str) -> tuple[str, str]:
    return {
        "critique": ("Faible à moyen", "Très élevée"),
        "majeur": ("Moyen", "Élevée"),
        "mineur": ("Faible", "Moyenne"),
    }.get(severity, ("À estimer", "À estimer"))


def _create_run_directory(output: Path, started_at: datetime, source_hash: str) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    base = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{source_hash[:8]}"
    candidate = output / base
    suffix = 1
    while candidate.exists():
        candidate = output / f"{base}-{suffix:02d}"
        suffix += 1
    candidate.mkdir()
    return candidate


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _evidence(record: FileRecord, start_line: int, end_line: int | None = None) -> EvidenceRef:
    return EvidenceRef(
        path=record.path,
        start_line=start_line,
        end_line=end_line or start_line,
        sha256=record.sha256,
    )

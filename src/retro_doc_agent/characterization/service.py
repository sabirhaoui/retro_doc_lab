"""Extraction déterministe des faits de caractérisation."""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as element_tree
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retro_doc_agent import __version__
from retro_doc_agent.config import ToolConfig
from retro_doc_agent.models.characterization import (
    Characterization,
    Dependency,
    DocumentationSummary,
    Fact,
    InventoryFile,
    LanguageStats,
    SkippedFile,
    TestSummary,
)
from retro_doc_agent.models.report import EvidenceRef, RunManifest
from retro_doc_agent.scanner import ScanResult, scan_source
from retro_doc_agent.scanner.filesystem import FileRecord, ScannedText

LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".php": "PHP",
    ".py": "Python",
    ".pyi": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sql": "SQL",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}
MANIFESTS = {
    "cargo.toml": "Cargo",
    "composer.json": "Composer",
    "gemfile": "Bundler",
    "go.mod": "Go modules",
    "package.json": "npm",
    "pipfile": "Pipenv",
    "pom.xml": "Maven",
}
FRAMEWORKS = {
    "django": "Django",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "laravel/framework": "Laravel",
    "express": "Express",
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "spring-boot-starter-web": "Spring Web",
}
DATA_TECHNOLOGIES = {
    "alembic": ("migration", "Alembic"),
    "boto3": ("service externe", "AWS SDK for Python"),
    "celery": ("messagerie", "Celery"),
    "doctrine/orm": ("ORM", "Doctrine ORM"),
    "django": ("ORM", "Django ORM"),
    "kafka-python": ("messagerie", "Kafka"),
    "prisma": ("ORM", "Prisma"),
    "psycopg": ("base de données", "PostgreSQL"),
    "pika": ("messagerie", "RabbitMQ client"),
    "redis": ("cache/service externe", "Redis"),
    "requests": ("service externe", "Requests"),
    "sequelize": ("ORM", "Sequelize"),
    "sqlalchemy": ("ORM", "SQLAlchemy"),
    "stripe": ("service externe", "Stripe SDK"),
    "typeorm": ("ORM", "TypeORM"),
}
ENV_PATTERNS = (
    re.compile(r"""\bos\.(?:getenv|environ\.get)\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""\bos\.environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE),
)
REQUIREMENT_PATTERN = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(?:==|~=|>=|<=|!=|>|<)\s*([A-Za-z0-9.*!+_-]+)"
)
PYTHON_MAIN = re.compile(r"\bif\s+__name__\s*==\s*['\"]__main__['\"]\s*:")


def characterize(source_root: Path, output_root: Path, config: ToolConfig) -> Path:
    """Génère les artefacts de caractérisation sans écrire dans la source."""
    started_at = datetime.now(UTC)
    source = source_root.expanduser().resolve(strict=True)
    output = output_root.expanduser().resolve()
    if output == source or source in output.parents:
        raise ValueError("Le répertoire de sortie ne peut pas être situé dans la source.")

    scanned_texts: dict[str, ScannedText] = {}
    detected_entry_points: list[Fact] = []
    detected_environment: dict[str, list[EvidenceRef]] = defaultdict(list)

    def retain_metadata(text_file: ScannedText) -> None:
        if _is_manifest(text_file.record.path) or _is_environment_example(text_file.record.path):
            scanned_texts[text_file.record.path] = text_file
        if _language(text_file.record.path) == "Python":
            detected_entry_points.extend(_python_entry_points(text_file))
        _collect_environment_variables(text_file, detected_environment)

    scan = scan_source(
        source,
        exclusions=config.exclude,
        max_file_bytes=config.max_file_bytes,
        on_text_file=retain_metadata,
    )
    report = _build_characterization(
        scan, scanned_texts, detected_entry_points, detected_environment
    )
    run_directory = _create_run_directory(output, started_at, scan.source_hash)
    characterization_directory = run_directory / "characterization"
    characterization_directory.mkdir()
    json_path = characterization_directory / "characterization.json"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path = characterization_directory / "characterization.md"
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")

    finished_at = datetime.now(UTC)
    duration = max(0.0, (finished_at - started_at).total_seconds())
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
        duration_seconds=duration,
        status="partial"
        if scan.uninspected_files or scan.limitations
        else "completed",
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
        "# Caractérisation du projet\n\n"
        "Cette exécution ne comprend que l'inventaire et la caractérisation.\n\n"
        "- [Rapport de caractérisation](characterization/characterization.md)\n"
        "- [Manifeste](run-manifest.json)\n",
        encoding="utf-8",
    )
    return run_directory


def _build_characterization(
    scan: ScanResult,
    scanned_texts: dict[str, ScannedText],
    detected_entry_points: list[Fact],
    detected_environment: dict[str, list[EvidenceRef]],
) -> Characterization:
    files = tuple(
        InventoryFile(
            path=item.path,
            size_bytes=item.size_bytes,
            sha256=item.sha256,
            line_count=item.line_count,
            language=_language(item.path),
        )
        for item in scan.files
    )
    language_data: dict[str, list[InventoryFile]] = defaultdict(list)
    for item in files:
        if item.language is not None:
            language_data[item.language].append(item)
    languages = tuple(
        LanguageStats(
            name=name,
            file_count=len(language_files),
            loc=sum(item.line_count for item in language_files),
            files=tuple(item.path for item in language_files),
            evidence=tuple(
                _evidence_for_path(item.path, scan.files)
                for item in language_files
                if item.line_count
            ),
        )
        for name, language_files in sorted(language_data.items())
    )

    package_managers, dependencies = _extract_dependencies(scanned_texts)
    frameworks = _framework_facts(dependencies)
    entry_points = _entry_point_facts(scan.files, detected_entry_points)
    infrastructure = _infrastructure_facts(scan.files)
    data_and_services = _data_facts(scan.files, dependencies)
    environment_variables = _environment_facts(detected_environment)
    test_files = tuple(
        item.path for item in scan.files if _is_test_file(item.path)
    )
    source_file_count = sum(1 for item in files if item.language is not None)
    ratio = len(test_files) / source_file_count if source_file_count else None
    test_frameworks = _test_frameworks(dependencies)
    test_commands = _test_commands(scanned_texts)
    docs_files = tuple(item.path for item in scan.files if _is_documentation(item.path))
    limitations = list(scan.limitations)
    limitations.extend(
        f"[NON VÉRIFIÉ] Contenu non inspecté ({item.reason}) : {item.path}"
        for item in scan.uninspected_files
    )
    limitations.append(
        "[NON VÉRIFIÉ] L'inventaire ne prouve pas l'absence de fichiers exclus."
    )
    limitations.append(
        "[NON VÉRIFIÉ] Révision Git, fichiers modifiés et couverture documentaire non comparés."
    )
    limitations.append(
        "[NON VÉRIFIÉ] Routes, workers et tâches dynamiques non déduits par la caractérisation."
    )
    limitations.append(
        "Les points d'entrée et variables d'environnement reposent sur des motifs textuels."
    )
    if not docs_files:
        limitations.append("[NON VÉRIFIÉ] Aucun fichier documentaire inclus n'a été détecté.")

    return Characterization(
        source_hash=scan.source_hash,
        source_hash_complete=scan.source_hash_complete,
        files=files,
        excluded_files=scan.excluded_files,
        uninspected_files=tuple(
            SkippedFile(path=item.path, reason=item.reason) for item in scan.uninspected_files
        ),
        languages=languages,
        frameworks=frameworks,
        package_managers=package_managers,
        dependencies=dependencies,
        entry_points=entry_points,
        infrastructure=infrastructure,
        data_and_services=data_and_services,
        environment_variables=environment_variables,
        tests=TestSummary(
            present=bool(test_files),
            frameworks=test_frameworks,
            files=test_files,
            test_to_source_file_ratio=ratio,
            execution_commands=test_commands,
            evidence=tuple(
                _evidence_for_path(path, scan.files)
                for path in test_files[:50]
                if _record_for_path(path, scan.files).line_count
            ),
        ),
        documentation=DocumentationSummary(files=docs_files),
        limitations=tuple(sorted(set(limitations))),
    )


def _extract_dependencies(
    texts: dict[str, ScannedText],
) -> tuple[tuple[Fact, ...], tuple[Dependency, ...]]:
    managers: dict[str, list[EvidenceRef]] = defaultdict(list)
    dependencies: dict[tuple[str, str | None, str], list[EvidenceRef]] = defaultdict(list)
    path_names = {Path(path).name.casefold() for path in texts}
    js_manager = (
        "pnpm"
        if "pnpm-lock.yaml" in path_names
        else "Yarn"
        if "yarn.lock" in path_names
        else "npm"
    )
    for path, scanned in sorted(texts.items()):
        filename = Path(path).name.casefold()
        manager = MANIFESTS.get(filename)
        if filename == "package.json":
            manager = js_manager
        if filename == "pyproject.toml":
            manager = (
                "uv"
                if "uv.lock" in path_names
                else "Poetry"
                if "[tool.poetry" in scanned.text
                else "pip"
            )
        if filename.startswith("requirements") and filename.endswith(".txt"):
            manager = "pip"
        elif filename in {"pnpm-lock.yaml"}:
            manager = "pnpm"
        elif filename in {"yarn.lock"}:
            manager = "Yarn"
        elif filename in {"package-lock.json"}:
            manager = js_manager
        elif filename == "uv.lock":
            manager = "uv"
        if manager is not None:
            file_evidence = _file_evidence(scanned.record)
            if file_evidence is not None:
                managers[manager].append(file_evidence)
        manager_dependencies = _parse_manifest(filename, scanned.text, manager)
        for name, version in manager_dependencies:
            line = _line_containing(scanned.text, name)
            evidence = _evidence(scanned.record, line)
            dependencies[(name, version, manager or "manifest")].append(evidence)

    package_facts = tuple(
        Fact(name=name, category="gestionnaire de paquets", evidence=tuple(refs))
        for name, refs in sorted(managers.items())
    )
    dependency_facts = tuple(
        Dependency(
            name=name,
            version=version,
            manager=manager,
            evidence=tuple(sorted(refs, key=lambda ref: (ref.path, ref.start_line))),
        )
        for (name, version, manager), refs in sorted(dependencies.items())
    )
    return package_facts, dependency_facts


def _parse_manifest(
    filename: str, text: str, manager: str | None
) -> tuple[tuple[str, str | None], ...]:
    try:
        if filename == "pyproject.toml":
            data = tomllib.loads(text)
            dependency_strings: list[str] = []
            project = data.get("project", {})
            if isinstance(project, dict):
                dependency_strings.extend(_strings(project.get("dependencies")))
                optional = project.get("optional-dependencies", {})
                if isinstance(optional, dict):
                    for values in optional.values():
                        dependency_strings.extend(_strings(values))
            poetry = data.get("tool", {}).get("poetry", {})
            if isinstance(poetry, dict):
                poetry_dependencies = poetry.get("dependencies", {})
                if isinstance(poetry_dependencies, dict):
                    for name, value in poetry_dependencies.items():
                        if name.casefold() != "python":
                            version = (
                                value
                                if isinstance(value, str)
                                else _mapping(value).get("version")
                            )
                            if not isinstance(version, str):
                                version = None
                            dependency_strings.append(f"{name}{version or ''}")
            return tuple(_parse_dependency_string(value) for value in dependency_strings)
        if filename.startswith("requirements") and filename.endswith(".txt"):
            result = []
            for line in text.splitlines():
                match = REQUIREMENT_PATTERN.match(line)
                if match:
                    result.append((match.group(1), match.group(2)))
            return tuple(result)
        if filename == "package.json":
            data = _mapping(json.loads(text))
            return tuple(
                (name, version if isinstance(version, str) else None)
                for section in ("dependencies", "devDependencies", "peerDependencies")
                for name, version in _mapping(data.get(section)).items()
            )
        if filename == "composer.json":
            data = _mapping(json.loads(text))
            return tuple(
                (name, version if isinstance(version, str) else None)
                for section in ("require", "require-dev")
                for name, version in _mapping(data.get(section)).items()
                if name != "php"
            )
        if filename == "pom.xml":
            root = element_tree.fromstring(text)
            parsed = []
            for dependency in root.iter():
                if dependency.tag.rsplit("}", 1)[-1] != "dependency":
                    continue
                values = {
                    child.tag.rsplit("}", 1)[-1]: child.text
                    for child in dependency
                    if child.text
                }
                if values.get("artifactId"):
                    parsed.append((values["artifactId"], values.get("version")))
            return tuple(parsed)
        if filename == "go.mod":
            return tuple(
                (match.group(1), match.group(2))
                for line in text.splitlines()
                if (match := re.match(r"\s*([A-Za-z0-9._/-]+)\s+v([^\s]+)", line))
            )
        if filename == "cargo.toml":
            data = tomllib.loads(text)
            return tuple(
                (
                    name,
                    version
                    if isinstance(version, str)
                    else _mapping(version).get("version")
                    if isinstance(_mapping(version).get("version"), str)
                    else None,
                )
                for section in ("dependencies", "dev-dependencies")
                for name, version in _mapping(data.get(section)).items()
            )
    except (ValueError, TypeError, KeyError, tomllib.TOMLDecodeError, element_tree.ParseError):
        return ()
    del manager
    return ()


def _parse_dependency_string(value: str) -> tuple[str, str | None]:
    match = REQUIREMENT_PATTERN.match(value)
    if match:
        return match.group(1), match.group(2)
    name = re.match(r"^([A-Za-z0-9_.-]+)", value)
    if not name:
        return value, None
    version = value[name.end() :].strip()
    return name.group(1), version or None


def _framework_facts(dependencies: tuple[Dependency, ...]) -> tuple[Fact, ...]:
    facts: dict[str, list[EvidenceRef]] = defaultdict(list)
    for dependency in dependencies:
        normalized = dependency.name.casefold()
        framework = FRAMEWORKS.get(normalized)
        if framework:
            facts[framework].extend(dependency.evidence)
    return tuple(
        Fact(
            name=name,
            category="framework",
            evidence=tuple(sorted(set(refs), key=lambda ref: (ref.path, ref.start_line))),
        )
        for name, refs in sorted(facts.items())
    )


def _entry_point_facts(
    files: tuple[FileRecord, ...], observed: list[Fact]
) -> tuple[Fact, ...]:
    facts = list(observed)
    inferred_names = {"app.py", "cli.py", "index.ts", "main.py", "server.py"}
    for record in files:
        if Path(record.path).name.casefold() in inferred_names and not any(
            fact.name == record.path for fact in facts
        ):
            if record.line_count:
                evidence: tuple[EvidenceRef, ...] = (_evidence(record, 1),)
            else:
                evidence = ()
            facts.append(
                Fact(
                    name=record.path,
                    category="candidat point d'entrée",
                    certainty="inférence",
                    detail=(
                        "Le nom du fichier suggère un point d'entrée ; "
                        "le rôle n'est pas confirmé."
                    ),
                    evidence=evidence,
                )
            )
    return tuple(sorted(facts, key=lambda fact: (fact.name, fact.category)))


def _infrastructure_facts(files: tuple[FileRecord, ...]) -> tuple[Fact, ...]:
    facts = []
    for record in files:
        path = record.path.casefold()
        name = Path(path).name
        category: str | None = None
        if name == "dockerfile" or name.startswith("dockerfile."):
            category = "Docker"
        elif name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            category = "Docker Compose"
        elif path.startswith(".github/workflows/"):
            category = "GitHub Actions"
        elif name == ".gitlab-ci.yml":
            category = "GitLab CI"
        elif path.startswith(("k8s/", "kubernetes/")) or "/templates/" in path:
            category = "Kubernetes/Helm (candidat)"
        elif name in {"makefile", "justfile"} or path.startswith("scripts/"):
            category = "script/build"
        if category and record.line_count:
            facts.append(
                Fact(
                    name=record.path,
                    category=category,
                    evidence=(_evidence(record, 1, record.line_count),),
                )
            )
    return tuple(sorted(facts, key=lambda fact: (fact.category, fact.name)))


def _data_facts(
    files: tuple[FileRecord, ...], dependencies: tuple[Dependency, ...]
) -> tuple[Fact, ...]:
    facts: list[Fact] = []
    for dependency in dependencies:
        match = DATA_TECHNOLOGIES.get(dependency.name.casefold())
        if match:
            category, label = match
            facts.append(
                Fact(
                    name=label,
                    category=category,
                    evidence=dependency.evidence,
                )
            )
    for record in files:
        path = record.path.casefold()
        if path.endswith(".sql") or "migration" in path or "migrations" in path:
            if record.line_count:
                category = "schéma SQL" if path.endswith(".sql") else "migration (candidat)"
                facts.append(
                    Fact(
                        name=record.path,
                        category=category,
                        evidence=(_evidence(record, 1, record.line_count),),
                    )
                )
    return tuple(
        sorted(
            facts,
            key=lambda fact: (
                fact.category,
                fact.name,
                tuple((item.path, item.start_line) for item in fact.evidence),
            ),
        )
    )


def _environment_facts(
    values: dict[str, list[EvidenceRef]]
) -> tuple[Fact, ...]:
    return tuple(
        Fact(
            name=name,
            category="variable d'environnement (nom uniquement)",
            certainty="inférence",
            detail="Nom détecté par motif textuel ; l'utilisation à l'exécution n'est pas prouvée.",
            evidence=tuple(sorted(set(refs), key=lambda ref: (ref.path, ref.start_line))),
        )
        for name, refs in sorted(values.items())
    )


def _test_frameworks(dependencies: tuple[Dependency, ...]) -> tuple[Fact, ...]:
    known = {
        "jest": "Jest",
        "phpunit/phpunit": "PHPUnit",
        "pytest": "pytest",
        "vitest": "Vitest",
    }
    facts: dict[str, list[EvidenceRef]] = defaultdict(list)
    for dependency in dependencies:
        framework = known.get(dependency.name.casefold())
        if framework:
            facts[framework].extend(dependency.evidence)
    return tuple(
        Fact(
            name=name,
            category="framework de test",
            evidence=tuple(sorted(set(refs), key=lambda ref: (ref.path, ref.start_line))),
        )
        for name, refs in sorted(facts.items())
    )


def _test_commands(texts: dict[str, ScannedText]) -> tuple[Fact, ...]:
    commands: list[Fact] = []
    for path, scanned in texts.items():
        if Path(path).name.casefold() == "package.json":
            try:
                scripts = _mapping(_mapping(json.loads(scanned.text)).get("scripts"))
            except (ValueError, TypeError):
                continue
            if "test" in scripts:
                commands.append(
                    Fact(
                        name="npm test",
                        category="commande de test déclarée",
                        evidence=(
                            _evidence(
                                scanned.record,
                                _line_containing(scanned.text, '"test"'),
                            ),
                        ),
                    )
                )
    return tuple(sorted(commands, key=lambda fact: fact.name))


def _python_entry_points(scanned: ScannedText) -> list[Fact]:
    facts = []
    for line_number, line in enumerate(scanned.text.splitlines(), start=1):
        if PYTHON_MAIN.search(line):
            facts.append(
                Fact(
                    name=scanned.record.path,
                    category="point d'entrée Python",
                    certainty="inférence",
                    detail="Motif textuel Python détecté ; l'appel effectif n'est pas prouvé.",
                    evidence=(_evidence(scanned.record, line_number),),
                )
            )
    return facts


def _collect_environment_variables(
    scanned: ScannedText, facts: dict[str, list[EvidenceRef]]
) -> None:
    for line_number, line in enumerate(scanned.text.splitlines(), start=1):
        patterns: tuple[re.Pattern[str], ...] = ENV_PATTERNS[:3]
        if _is_environment_example(scanned.record.path):
            patterns = patterns + ENV_PATTERNS[3:]
        for pattern in patterns:
            for match in pattern.finditer(line):
                facts[match.group(1)].append(_evidence(scanned.record, line_number))


def _is_test_file(path: str) -> bool:
    normalized = path.casefold()
    name = Path(normalized).name
    return (
        any(part in {"test", "tests", "__tests__"} for part in Path(normalized).parts)
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _is_documentation(path: str) -> bool:
    normalized = path.casefold()
    name = Path(normalized).name
    return (
        name.startswith("readme")
        or name.startswith("changelog")
        or name.startswith("contributing")
        or name.endswith(".md")
        or "/docs/" in f"/{normalized}/"
        or "/adr/" in f"/{normalized}/"
    )


def _is_manifest(path: str) -> bool:
    name = Path(path).name.casefold()
    return (
        name in MANIFESTS
        or name in {"pyproject.toml", "requirements.txt", "pipfile.lock", "uv.lock"}
        or name.startswith("requirements") and name.endswith(".txt")
        or name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
    )


def _is_environment_example(path: str) -> bool:
    name = Path(path).name.casefold()
    return name in {".env.example", ".env.sample", ".env.template"} or name.endswith(
        ".env.example"
    )


def _language(path: str) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.casefold())


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _line_containing(text: str, needle: str) -> int:
    for line_number, line in enumerate(text.splitlines(), start=1):
        if needle.casefold() in line.casefold():
            return line_number
    return 1


def _evidence(record: FileRecord, start_line: int, end_line: int | None = None) -> EvidenceRef:
    line = max(start_line, 1)
    end = max(end_line or line, line)
    return EvidenceRef(
        path=record.path,
        start_line=line,
        end_line=end,
        sha256=record.sha256,
    )


def _file_evidence(record: FileRecord) -> EvidenceRef | None:
    if not record.line_count:
        return None
    return _evidence(record, 1, record.line_count)


def _evidence_for_path(path: str, files: tuple[FileRecord, ...]) -> EvidenceRef:
    record = _record_for_path(path, files)
    evidence = _file_evidence(record)
    if evidence is None:
        raise ValueError(f"Aucune ligne de preuve disponible pour {path}.")
    return evidence


def _record_for_path(path: str, files: tuple[FileRecord, ...]) -> FileRecord:
    return next(item for item in files if item.path == path)


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


def _render_markdown(report: Characterization) -> str:
    lines = [
        "# Caractérisation du projet",
        "",
        f"- Empreinte du périmètre inspecté : `{report.source_hash}`",
        f"- Empreinte complète : **{'oui' if report.source_hash_complete else 'non'}**",
        f"- Fichiers inspectés : **{len(report.files)}**",
        f"- Fichiers exclus : **{len(report.excluded_files)}**",
        f"- Fichiers non inspectés : **{len(report.uninspected_files)}**",
        "",
        "## Langages et volumétrie",
        "",
        "| Langage | Fichiers | LOC | Preuves |",
        "|---|---:|---:|---|",
    ]
    for language in report.languages:
        evidence = ", ".join(
            f"`{item.path}:{item.start_line}`" for item in language.evidence[:10]
        ) or "[NON VÉRIFIÉ]"
        lines.append(
            f"| {language.name} | {language.file_count} | {language.loc} | {evidence} |"
        )
    lines.extend(["", "## Inventaire des fichiers", ""])
    lines.extend(["| Chemin | Octets | LOC | Preuve |", "|---|---:|---:|---|"])
    for item in sorted(report.files, key=lambda value: (-value.size_bytes, value.path))[:30]:
        proof = f"`{item.path}:1`" if item.line_count else "[NON VÉRIFIÉ — fichier vide]"
        lines.append(f"| `{item.path}` | {item.size_bytes} | {item.line_count} | {proof} |")
    if len(report.files) > 30:
        lines.append(
            f"\nLe tableau présente les 30 fichiers les plus volumineux ; "
            f"l'inventaire JSON contient les {len(report.files)} fichiers inspectés."
        )
    lines.extend(["", "## Dépendances", ""])
    if report.dependencies:
        lines.extend(
            [
                "| Gestionnaire | Dépendance | Version déclarée | Preuve |",
                "|---|---|---|---|",
            ]
        )
        for dependency in report.dependencies:
            version = dependency.version or "[NON VÉRIFIÉ]"
            evidence = ", ".join(
                f"`{item.path}:{item.start_line}`" for item in dependency.evidence
            )
            lines.append(
                f"| {dependency.manager} | {dependency.name} | {version} | {evidence} |"
            )
    else:
        lines.append("[NON VÉRIFIÉ] Aucune dépendance prise en charge n'a été extraite.")
    _append_fact_section(lines, "Gestionnaires de paquets", report.package_managers)
    _append_fact_section(lines, "Frameworks", report.frameworks)
    _append_fact_section(lines, "Points d'entrée", report.entry_points)
    _append_fact_section(lines, "Infrastructure et delivery", report.infrastructure)
    _append_fact_section(lines, "Données et services", report.data_and_services)
    _append_fact_section(
        lines,
        "Variables d'environnement (noms uniquement)",
        report.environment_variables,
    )
    ratio = (
        report.tests.test_to_source_file_ratio
        if report.tests.test_to_source_file_ratio is not None
        else "[NON VÉRIFIÉ]"
    )
    test_frameworks = ", ".join(fact.name for fact in report.tests.frameworks) or "[NON VÉRIFIÉ]"
    test_commands = (
        ", ".join(fact.name for fact in report.tests.execution_commands) or "[NON VÉRIFIÉ]"
    )
    lines.extend(
        [
            "",
            "## Tests",
            "",
            f"- Présence détectée : **{'oui' if report.tests.present else 'non'}**",
            f"- Fichiers candidats : {len(report.tests.files)}",
            f"- Ratio fichiers de test/source : {ratio}",
            f"- Frameworks : {test_frameworks}",
            f"- Commandes détectées : {test_commands}",
        ]
    )
    if report.tests.files:
        lines.append(
            "- Preuves : "
            + ", ".join(
                f"`{item.path}:{item.start_line}`" for item in report.tests.evidence[:20]
            )
        )
    for fact in report.tests.frameworks + report.tests.execution_commands:
        evidence = ", ".join(
            f"`{item.path}:{item.start_line}`" for item in fact.evidence
        ) or "[NON VÉRIFIÉ]"
        lines.append(f"- Preuve de **{fact.name}** : {evidence}")
    lines.extend(["", "## Documentation existante", ""])
    if report.documentation.files:
        lines.extend(f"- `{path}`" for path in report.documentation.files)
    else:
        lines.append("[NON VÉRIFIÉ] Aucun document inclus dans le périmètre.")
    lines.extend(["", "## Périmètre et limites", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    if report.uninspected_files:
        lines.extend(["", "### Fichiers non inspectés", ""])
        lines.extend(
            f"- `{item.path}` — {item.reason}" for item in report.uninspected_files
        )
    lines.append("")
    return "\n".join(lines)


def _append_fact_section(lines: list[str], title: str, facts: tuple[Fact, ...]) -> None:
    lines.extend(["", f"## {title}", ""])
    if not facts:
        lines.append("[NON VÉRIFIÉ] Aucun fait détecté par les règles statiques disponibles.")
        return
    for fact in facts:
        evidence = ", ".join(
            f"`{item.path}:{item.start_line}-{item.end_line}`" for item in fact.evidence
        )
        details = f" — {fact.detail}" if fact.detail else ""
        proof = evidence or "[NON VÉRIFIÉ]"
        lines.append(f"- **{fact.name}** ({fact.certainty}){details} — {proof}")

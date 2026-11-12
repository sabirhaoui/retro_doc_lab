"""Schéma versionné de caractérisation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from retro_doc_agent.models.report import EvidenceRef


class InventoryFile(BaseModel):
    """Métadonnées d'un fichier source inspecté."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_count: int = Field(ge=0)
    language: str | None = None


class LanguageStats(BaseModel):
    """Volumétrie calculée pour un langage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    file_count: int = Field(ge=0)
    loc: int = Field(ge=0)
    files: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...] = ()


class Fact(BaseModel):
    """Fait détecté, qualifié et accompagné de preuves."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    category: str
    certainty: Literal["observé", "inférence", "non_vérifié"] = "observé"
    detail: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()


class Dependency(BaseModel):
    """Dépendance extraite d'un manifeste sans exécuter de gestionnaire."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str | None = None
    manager: str
    evidence: tuple[EvidenceRef, ...]


class TestSummary(BaseModel):
    """Résumé de la présence et des indices relatifs aux tests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    present: bool
    frameworks: tuple[Fact, ...]
    files: tuple[str, ...]
    test_to_source_file_ratio: float | None = Field(default=None, ge=0)
    execution_commands: tuple[Fact, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()


class DocumentationSummary(BaseModel):
    """Inventaire documentaire existant sans jugement non étayé."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class SkippedFile(BaseModel):
    """Fichier dont le contenu n'a pas été analysé, avec cause."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    reason: str


class Characterization(BaseModel):
    """Rapport de caractérisation JSON versionné."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash_complete: bool
    files: tuple[InventoryFile, ...]
    excluded_files: tuple[str, ...]
    uninspected_files: tuple[SkippedFile, ...]
    languages: tuple[LanguageStats, ...]
    frameworks: tuple[Fact, ...]
    package_managers: tuple[Fact, ...]
    dependencies: tuple[Dependency, ...]
    entry_points: tuple[Fact, ...]
    infrastructure: tuple[Fact, ...]
    data_and_services: tuple[Fact, ...]
    environment_variables: tuple[Fact, ...]
    tests: TestSummary
    documentation: DocumentationSummary
    limitations: tuple[str, ...]

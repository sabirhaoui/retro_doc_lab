"""Schémas de l'analyse statique et de l'audit d'architecture."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from retro_doc_agent.models.characterization import Fact
from retro_doc_agent.models.report import EvidenceRef


class ModuleFact(BaseModel):
    """Module Python observé sans exécution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    path: str
    line_count: int = Field(ge=0)
    evidence: tuple[EvidenceRef, ...] = ()


class ImportEdge(BaseModel):
    """Import résolu entre deux modules du périmètre."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    target: str
    evidence: EvidenceRef


class FunctionFact(BaseModel):
    """Fonction/méthode déclarée et métriques AST."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    module: str
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    complexity: int = Field(ge=1)
    entrypoint_kind: str | None = None
    evidence: EvidenceRef


class CallEdge(BaseModel):
    """Appel résolu ou non entre fonctions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    caller: str
    callee_expression: str
    target: str | None = None
    evidence: EvidenceRef


class SecretSignal(BaseModel):
    """Signal de valeur secrète potentielle, valeur omise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variable_name: str
    evidence: EvidenceRef


class PythonAnalysis(BaseModel):
    """Résultat de l'analyse AST Python."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    modules: tuple[ModuleFact, ...]
    imports: tuple[ImportEdge, ...]
    functions: tuple[FunctionFact, ...]
    calls: tuple[CallEdge, ...]
    entrypoints: tuple[FunctionFact, ...]
    secret_signals: tuple[SecretSignal, ...]
    unparsed_files: tuple[str, ...]
    limitations: tuple[str, ...]


class Finding(BaseModel):
    """Constat numéroté, preuve, impact et recommandation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    severity: Literal["critique", "majeur", "mineur"]
    category: Literal[
        "couplage",
        "cycles de dépendances",
        "couche violée",
        "duplication",
        "dette",
        "sécurité",
        "observabilité",
        "testabilité",
        "déploiement",
    ]
    title: str
    impact: str
    recommendation: str
    evidence: tuple[EvidenceRef, ...]


class ArchitectureAudit(BaseModel):
    """Données d'audit consommées par les rendus Markdown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    modules: tuple[ModuleFact, ...]
    imports: tuple[ImportEdge, ...]
    functions: tuple[FunctionFact, ...]
    calls: tuple[CallEdge, ...]
    cycles: tuple[tuple[str, ...], ...]
    findings: tuple[Finding, ...]
    documentation_files: tuple[str, ...]
    documented_modules: tuple[Fact, ...]
    undocumented_modules: tuple[Fact, ...]
    limitations: tuple[str, ...]

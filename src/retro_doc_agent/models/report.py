"""Modèles de preuve et manifeste d'exécution."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    """Référence résoluble vers une plage de lignes source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunManifest(BaseModel):
    """Métadonnées versionnées d'une exécution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    tool_version: str
    run_id: str
    source_root: str
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    finished_at: datetime
    options: dict[str, str | int | bool | None]
    duration_seconds: float = Field(ge=0)
    source_revision: str | None = None
    status: Literal["completed", "failed", "partial"] = "completed"
    limitations: tuple[str, ...] = ()

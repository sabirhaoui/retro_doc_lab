"""Chargement et validation de la configuration TOML."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigError(Exception):
    """Erreur de lecture ou de validation de la configuration."""


class ToolConfig(BaseModel):
    """Options globales versionnées de l'outil."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    source_root: Path | None = None
    output_root: Path = Path("output")
    max_file_bytes: int = Field(default=1_000_000, gt=0)
    exclude: tuple[str, ...] = (
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".env",
        "*.pem",
        "*.key",
    )
    llm_enabled: bool = False


def load_config(path: Path) -> ToolConfig:
    """Charge une configuration TOML et résout ses chemins relatifs."""
    config_path = path.expanduser().resolve()
    try:
        with config_path.open("rb") as stream:
            raw: dict[str, Any] = tomllib.load(stream)
    except OSError as exc:
        raise ConfigError(f"Impossible de lire la configuration « {config_path} ».") from exc
    except tomllib.TOMLDecodeError as exc:
        message = f"Le fichier de configuration « {config_path} » n'est pas un TOML valide."
        raise ConfigError(message) from exc

    try:
        config = ToolConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'configuration'}: {error['msg']}"
            for error in exc.errors(include_input=False)
        )
        raise ConfigError(f"Configuration invalide : {details}") from exc

    base = config_path.parent
    source_root = _resolve_path(config.source_root, base)
    output_root = _resolve_path(config.output_root, base)
    return config.model_copy(update={"source_root": source_root, "output_root": output_root})


def _resolve_path(value: Path | None, base: Path) -> Path | None:
    if value is None:
        return None
    expanded = value.expanduser()
    return (base / expanded).resolve() if not expanded.is_absolute() else expanded.resolve()

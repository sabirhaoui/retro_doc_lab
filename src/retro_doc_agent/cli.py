"""Interface en ligne de commande."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from retro_doc_agent.characterization import characterize as build_characterization
from retro_doc_agent.config import ConfigError, ToolConfig, load_config

app = typer.Typer(
    name="retro-doc-lab",
    help="Caractérise et documente statiquement un projet logiciel.",
    no_args_is_help=True,
    add_completion=False,
)


def _load_options(
    source_path: Path,
    config_path: Path,
    out: Path | None,
) -> tuple[Path, Path, ToolConfig]:
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    source = source_path.expanduser().resolve()
    if not source.is_dir():
        message = f"Le répertoire source n'existe pas ou n'est pas un dossier : {source}"
        typer.echo(message, err=True)
        raise typer.Exit(code=2)
    output = (out.expanduser().resolve() if out is not None else config.output_root)
    return source, output, config


def _pending(feature: str) -> None:
    typer.echo(
        f"La commande « {feature} » sera disponible dans un prochain lot d'implémentation.",
        err=True,
    )
    raise typer.Exit(code=3)


def _analysis_command(
    feature: str,
    source_path: Path,
    out: Path | None,
    no_llm: bool,
    max_sequences: int,
    config_path: Path,
) -> None:
    _, _, config = _load_options(source_path, config_path, out)
    if max_sequences < 1:
        typer.echo("--max-sequences doit être supérieur ou égal à 1.", err=True)
        raise typer.Exit(code=2)
    if no_llm and config.llm_enabled:
        config = config.model_copy(update={"llm_enabled": False})
    _pending(feature)


@app.command()
def analyze(
    source_path: Annotated[Path, typer.Argument(help="Répertoire source à analyser.")],
    out: Annotated[Path | None, typer.Option("--out", help="Répertoire de sortie.")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Désactive la synthèse LLM.")] = False,
    max_sequences: Annotated[
        int, typer.Option("--max-sequences", min=1, help="Nombre maximal de séquences.")
    ] = 5,
    config_path: Annotated[
        Path, typer.Option("--config", help="Fichier de configuration TOML.")
    ] = Path("retro_doc_lab.toml"),
) -> None:
    """Exécute le pipeline complet de rétro-documentation."""
    _analysis_command("analyze", source_path, out, no_llm, max_sequences, config_path)


@app.command()
def characterize(
    source_path: Annotated[Path, typer.Argument(help="Répertoire source à caractériser.")],
    out: Annotated[Path | None, typer.Option("--out", help="Répertoire de sortie.")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Désactive la synthèse LLM.")] = False,
    max_sequences: Annotated[int, typer.Option("--max-sequences", min=1)] = 5,
    config_path: Annotated[Path, typer.Option("--config")] = Path("retro_doc_lab.toml"),
) -> None:
    """Produit la caractérisation du projet."""
    _, _, config = _load_options(source_path, config_path, out)
    if max_sequences < 1:
        typer.echo("--max-sequences doit être supérieur ou égal à 1.", err=True)
        raise typer.Exit(code=2)
    if no_llm and config.llm_enabled:
        config = config.model_copy(update={"llm_enabled": False})
    output = out.expanduser().resolve() if out is not None else config.output_root
    try:
        run_directory = build_characterization(source_path, output, config)
    except (OSError, ValueError) as exc:
        typer.echo(f"Échec de la caractérisation : {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Caractérisation créée : {run_directory}")


@app.command()
def audit(
    source_path: Annotated[Path, typer.Argument(help="Répertoire source à auditer.")],
    out: Annotated[Path | None, typer.Option("--out", help="Répertoire de sortie.")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Désactive la synthèse LLM.")] = False,
    max_sequences: Annotated[int, typer.Option("--max-sequences", min=1)] = 5,
    config_path: Annotated[Path, typer.Option("--config")] = Path("retro_doc_lab.toml"),
) -> None:
    """Produit l'audit d'architecture."""
    _analysis_command("audit", source_path, out, no_llm, max_sequences, config_path)


@app.command()
def sequences(
    source_path: Annotated[Path, typer.Argument(help="Répertoire source à analyser.")],
    out: Annotated[Path | None, typer.Option("--out", help="Répertoire de sortie.")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Désactive la synthèse LLM.")] = False,
    max_sequences: Annotated[
        int, typer.Option("--max-sequences", min=1, help="Nombre maximal de séquences.")
    ] = 5,
    config_path: Annotated[Path, typer.Option("--config")] = Path("retro_doc_lab.toml"),
) -> None:
    """Génère les diagrammes des parcours principaux."""
    _analysis_command("sequences", source_path, out, no_llm, max_sequences, config_path)


@app.command()
def validate(
    output_dir: Annotated[Path, typer.Argument(help="Répertoire de sortie à valider.")],
) -> None:
    """Vérifie les schémas, preuves et diagrammes d'une exécution."""
    resolved = output_dir.expanduser().resolve()
    if not resolved.is_dir():
        typer.echo(f"Le répertoire de sortie n'existe pas : {resolved}", err=True)
        raise typer.Exit(code=2)
    typer.echo(
        "La validation des rapports sera disponible dans un prochain lot d'implémentation.",
        err=True,
    )
    raise typer.Exit(code=3)

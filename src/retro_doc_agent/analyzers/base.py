"""Contrat commun pour les analyseurs de langage."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from retro_doc_agent.scanner.filesystem import ScannedText


class Analyzer(Protocol):
    """Interface d'observation incrémentale des fichiers."""

    def supports(self, path: Path) -> bool:
        """Indique si l'analyseur reconnaît l'extension du fichier."""

    def observe(self, source_file: ScannedText) -> None:
        """Consomme un fichier textuel sans le modifier."""

"""Analyseurs statiques spécialisés par langage."""

from retro_doc_agent.analyzers.base import Analyzer
from retro_doc_agent.analyzers.python import PythonAnalyzer

__all__ = ["Analyzer", "PythonAnalyzer"]
"""Static analyzers: accept admitted text, never open or execute source."""

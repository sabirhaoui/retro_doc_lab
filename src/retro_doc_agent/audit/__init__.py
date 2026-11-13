"""Audit statique d'architecture."""

from retro_doc_agent.audit.service import audit as _audit
from retro_doc_agent.audit.service import run as _run

audit = _audit
run = _run

__all__ = ["audit", "run"]

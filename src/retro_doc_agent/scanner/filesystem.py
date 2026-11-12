"""Scanner déterministe qui ne suit pas les liens symboliques."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileRecord(BaseModel):
    """Métadonnées d'un fichier lisible du périmètre."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_count: int = Field(ge=0)
    status: Literal["inspected"] = "inspected"


class UninspectedFile(BaseModel):
    """Chemin exclu de lecture effective avec sa cause non sensible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    reason: str


class ScanResult(BaseModel):
    """Résultat déterministe du parcours de fichiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_root: Path
    files: tuple[FileRecord, ...]
    excluded_files: tuple[str, ...]
    uninspected_files: tuple[UninspectedFile, ...]
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash_complete: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ScannedText:
    """Texte transitoire remis au consommateur puis libéré."""

    record: FileRecord
    text: str


@dataclass(frozen=True)
class _IgnoreRule:
    base: str
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool


DEFAULT_EXCLUDES = (
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    "*.pem",
    "*.key",
    ".env",
)


def scan_source(
    source_root: Path,
    *,
    exclusions: tuple[str, ...] = (),
    max_file_bytes: int = 1_000_000,
    on_text_file: Callable[[ScannedText], None] | None = None,
) -> ScanResult:
    """Inventorie les fichiers textuels inclus et appelle le consommateur sans les retenir."""
    root = source_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Le chemin source n'est pas un dossier : {root}")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes doit être supérieur à zéro.")

    excluded_patterns = DEFAULT_EXCLUDES + exclusions
    records: list[FileRecord] = []
    excluded: set[str] = set()
    uninspected: list[UninspectedFile] = []
    limitations: set[str] = set()
    source_digest = hashlib.sha256()
    pending_directories: list[tuple[Path, tuple[_IgnoreRule, ...]]] = [(root, ())]

    while pending_directories:
        directory, inherited_rules = pending_directories.pop()
        relative_directory = _relative_path(root, directory)
        local_rules = _read_ignore_rules(
            root,
            directory,
            relative_directory,
            excluded_patterns,
            max_file_bytes,
            excluded,
            uninspected,
            limitations,
        )
        rules = inherited_rules + local_rules
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: (entry.name.casefold(), entry.name))
        except OSError:
            uninspected.append(
                UninspectedFile(path=relative_directory or ".", reason="répertoire illisible")
            )
            continue

        directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative = _relative_path(root, path)
            try:
                if entry.is_symlink():
                    excluded.add(relative)
                    limitations.add("Liens symboliques non suivis.")
                    continue
                is_directory = entry.is_dir(follow_symlinks=False)
                ignored = _is_user_excluded(relative, excluded_patterns) or _is_git_ignored(
                    relative, is_directory, rules
                )
                if ignored:
                    excluded.add(relative)
                    continue
                if is_directory:
                    directories.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    excluded.add(relative)
                    limitations.add("Fichiers spéciaux ignorés.")
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                uninspected.append(UninspectedFile(path=relative, reason="métadonnées illisibles"))
                continue

            if size > max_file_bytes:
                uninspected.append(
                    UninspectedFile(path=relative, reason="taille maximale dépassée")
                )
                continue
            try:
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as stream:
                    opened_stat = os.fstat(stream.fileno())
                    same_file = True
                    if getattr(os, "O_NOFOLLOW", 0):
                        current_stat = entry.stat(follow_symlinks=False)
                        same_file = (
                            opened_stat.st_dev == current_stat.st_dev
                            and opened_stat.st_ino == current_stat.st_ino
                        )
                    if not stat.S_ISREG(opened_stat.st_mode) or not same_file:
                        excluded.add(relative)
                        limitations.add("Fichiers remplacés ou non réguliers ignorés.")
                        continue
                    content = stream.read(max_file_bytes + 1)
            except OSError:
                uninspected.append(UninspectedFile(path=relative, reason="fichier illisible"))
                continue
            if len(content) > max_file_bytes:
                uninspected.append(
                    UninspectedFile(path=relative, reason="taille maximale dépassée")
                )
                continue
            digest = hashlib.sha256(content).hexdigest()
            source_digest.update(relative.encode("utf-8", errors="replace"))
            source_digest.update(b"\0")
            source_digest.update(bytes.fromhex(digest))
            if b"\0" in content:
                excluded.add(relative)
                limitations.add("Fichiers binaires non analysés.")
                continue
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                uninspected.append(UninspectedFile(path=relative, reason="encodage UTF-8 invalide"))
                continue

            record = FileRecord(
                path=relative,
                size_bytes=size,
                sha256=digest,
                line_count=len(text.splitlines()),
            )
            records.append(record)
            if on_text_file is not None:
                on_text_file(ScannedText(record=record, text=text))

        pending_directories.extend((path, rules) for path in reversed(directories))

    records.sort(key=lambda item: item.path)
    uninspected.sort(key=lambda item: item.path)
    return ScanResult(
        source_root=root,
        files=tuple(records),
        excluded_files=tuple(sorted(excluded)),
        uninspected_files=tuple(uninspected),
        source_hash=source_digest.hexdigest(),
        source_hash_complete=not uninspected,
        limitations=tuple(sorted(limitations)),
    )


def _read_ignore_rules(
    root: Path,
    directory: Path,
    relative_directory: str,
    exclusions: tuple[str, ...],
    max_file_bytes: int,
    excluded: set[str],
    uninspected: list[UninspectedFile],
    limitations: set[str],
) -> tuple[_IgnoreRule, ...]:
    ignore_file = directory / ".gitignore"
    relative_ignore = _relative_path(root, ignore_file)
    if _is_user_excluded(relative_ignore, exclusions):
        excluded.add(relative_ignore)
        return ()
    if ignore_file.is_symlink():
        excluded.add(relative_ignore)
        limitations.add("Liens symboliques non suivis.")
        return ()
    if not ignore_file.is_file():
        return ()
    try:
        if ignore_file.stat().st_size > max_file_bytes:
            uninspected.append(
                UninspectedFile(path=relative_ignore, reason="fichier .gitignore trop volumineux")
            )
            return ()
        lines = ignore_file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        uninspected.append(
            UninspectedFile(path=relative_ignore, reason="fichier .gitignore illisible")
        )
        return ()

    rules: list[_IgnoreRule] = []
    for raw_line in lines:
        pattern = raw_line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        directory_only = pattern.endswith("/")
        pattern = pattern.strip("/")
        if pattern:
            rules.append(
                _IgnoreRule(
                    base=relative_directory,
                    pattern=pattern,
                    negated=negated,
                    directory_only=directory_only,
                    anchored=raw_line.startswith("/") or "/" in pattern,
                )
            )
    return tuple(rules)


def _is_user_excluded(relative: str, patterns: tuple[str, ...]) -> bool:
    parts = relative.split("/")
    for pattern in patterns:
        normalized = pattern.replace("\\", "/").rstrip("/")
        if not normalized:
            continue
        if fnmatch.fnmatchcase(relative, normalized):
            return True
        if any(fnmatch.fnmatchcase(part, normalized) for part in parts):
            return True
        if "/" in normalized and any(
            fnmatch.fnmatchcase("/".join(parts[:index]), normalized)
            for index in range(1, len(parts))
        ):
            return True
    return False


def _is_git_ignored(
    relative: str, is_directory: bool, rules: tuple[_IgnoreRule, ...]
) -> bool:
    ignored = False
    for rule in rules:
        if rule.base and not relative.startswith(f"{rule.base}/"):
            continue
        local = relative[len(rule.base) + 1 :] if rule.base else relative
        candidates = [local]
        if rule.directory_only and not is_directory:
            parts = local.split("/")
            candidates = ["/".join(parts[:index]) for index in range(1, len(parts))]
        matched = False
        for candidate in candidates:
            if rule.anchored:
                matched = fnmatch.fnmatchcase(candidate, rule.pattern)
            else:
                matched = any(
                    fnmatch.fnmatchcase(part, rule.pattern) for part in candidate.split("/")
                )
            if matched:
                break
        if matched:
            ignored = not rule.negated
    return ignored


def _relative_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return "" if relative == Path(".") else relative.as_posix()

"""Safe, deterministic source inventory and bounded batch planning."""

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath


DEFAULT_EXTENSIONS = [
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".java", ".kt",
    ".go", ".rs", ".cs", ".fs", ".vb", ".php", ".rb", ".swift", ".m",
    ".mm", ".c", ".h", ".cc", ".cpp", ".hpp", ".sql", ".sh", ".ps1",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".graphql", ".gql",
    ".md", ".mdx",
]
DEFAULT_EXCLUSIONS = [
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist",
    "build", ".env", "*.pem", "*.key",
]
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")


class InventoryError(ValueError):
    """Raised when the inventory configuration violates safety constraints."""


def _is_within(path, parent):
    return path == parent or parent in path.parents


def load_config(config_path):
    config_path = config_path.resolve()
    repo_root = config_path.parent.parent.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise InventoryError("config must use schema_version 1")
    if config.get("source_access") != "read-only":
        raise InventoryError("source_access must be read-only")
    if config.get("network") != "disabled":
        raise InventoryError("network must be disabled")

    source_value = config.get("source_root")
    if not isinstance(source_value, str) or not source_value:
        raise InventoryError("source_root must be an absolute path")
    source = Path(source_value)
    if not source.is_absolute() or not source.is_dir():
        raise InventoryError("source_root must be an existing absolute directory")
    source = source.resolve()
    if _is_within(source, repo_root) or _is_within(repo_root, source):
        raise InventoryError("source_root and the agent repository must be separate")

    output_value = config.get("output_root")
    if not isinstance(output_value, str) or not output_value:
        raise InventoryError("output_root must be a nonempty relative path")
    output_relative = Path(output_value)
    if output_relative.is_absolute():
        raise InventoryError("output_root must be relative to the agent repository")
    output_root = (repo_root / output_relative).resolve()
    if not _is_within(output_root, repo_root) or output_root == repo_root:
        raise InventoryError("output_root must be confined to the agent repository")
    if _is_within(output_root, source) or _is_within(source, output_root):
        raise InventoryError("output_root and source_root must not overlap")

    config = dict(config)
    config["_source_root"] = source
    config["_output_root"] = output_root
    config["_repo_root"] = repo_root
    config["exclude"] = _string_list(config.get("exclude", DEFAULT_EXCLUSIONS), "exclude")
    extensions = _string_list(
        config.get("source_extensions", DEFAULT_EXTENSIONS), "source_extensions"
    )
    normalized_extensions = sorted({item.lower() for item in extensions})
    if any(not item.startswith(".") or item == "." for item in normalized_extensions):
        raise InventoryError("source_extensions entries must be file extensions")
    config["source_extensions"] = normalized_extensions

    for key in ("max_file_bytes", "max_batch_bytes", "max_batch_files"):
        value = config.get(key)
        if type(value) is not int or value <= 0:
            raise InventoryError(f"{key} must be a positive integer")
    if config["max_batch_bytes"] < config["max_file_bytes"]:
        raise InventoryError("max_batch_bytes must be at least max_file_bytes")
    return config, repo_root


def _string_list(value, name):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise InventoryError(f"{name} must be a list of nonempty strings")
    return value


def _excluded(relative_path, patterns):
    posix_path = relative_path.as_posix()
    return any(
        fnmatch.fnmatchcase(part, pattern)
        or fnmatch.fnmatchcase(posix_path, pattern)
        for pattern in patterns
        for part in relative_path.parts
    )


def _inspect_file(path, relative_path, max_file_bytes):
    relative = relative_path.as_posix()
    try:
        before = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            return {"path": relative, "status": "symlink_or_nonfile", "bytes": before.st_size}
        if before.st_size > max_file_bytes:
            return {"path": relative, "status": "oversized", "bytes": before.st_size}
        with path.open("rb") as source_file:
            data = source_file.read(max_file_bytes + 1)
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        return {
            "path": relative,
            "status": "unreadable",
            "bytes": None,
            "error": type(exc).__name__,
        }

    if len(data) > max_file_bytes:
        return {"path": relative, "status": "oversized", "bytes": len(data)}
    if (
        stat.S_ISLNK(after.st_mode)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(data) != after.st_size
    ):
        return {"path": relative, "status": "changed_during_read", "bytes": len(data)}
    if b"\0" in data:
        return {"path": relative, "status": "binary", "bytes": len(data)}

    return {
        "path": relative,
        "status": "inspected",
        "bytes": len(data),
        "lines": len(data.splitlines()),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _scan(source_root, config):
    exclusions = config["exclude"]
    extensions = set(config["source_extensions"])
    max_bytes = config["max_file_bytes"]
    pending = [source_root]
    entries = []
    excluded_paths = []
    errors = []
    candidate_count = 0

    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                children = sorted(scan, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            relative = directory.relative_to(source_root).as_posix()
            errors.append(f"Cannot list {relative or '.'}: {type(exc).__name__}")
            continue

        directories = []
        for child in children:
            path = Path(child.path)
            relative = PurePosixPath(path.relative_to(source_root).as_posix())
            if _excluded(relative, exclusions):
                excluded_paths.append(relative.as_posix())
                continue
            try:
                if child.is_symlink():
                    excluded_paths.append(relative.as_posix())
                elif child.is_dir(follow_symlinks=False):
                    directories.append(path)
                elif child.is_file(follow_symlinks=False):
                    if path.suffix.lower() not in extensions:
                        continue
                    candidate_count += 1
                    item = _inspect_file(path, relative, max_bytes)
                    entries.append(item)
                    if item["status"] == "unreadable":
                        errors.append(
                            f"Cannot read {relative.as_posix()}: {item['error']}"
                        )
            except OSError as exc:
                candidate_count += int(path.suffix.lower() in extensions)
                entries.append({
                    "path": relative.as_posix(),
                    "status": "unreadable",
                    "bytes": None,
                })
                errors.append(f"Cannot inspect {relative.as_posix()}: {type(exc).__name__}")
        pending.extend(reversed(directories))

    entries.sort(key=lambda item: item["path"].casefold())
    excluded_paths.sort(key=str.casefold)
    return entries, excluded_paths, errors, candidate_count


def _make_batches(entries, max_files, max_bytes):
    batches = []
    by_component = {}
    for item in entries:
        if item["status"] == "inspected":
            path = PurePosixPath(item["path"])
            component = path.parts[0] if len(path.parts) > 1 else "(root)"
            by_component.setdefault(component, []).append(item)

    for component in sorted(by_component, key=str.casefold):
        current = []
        current_bytes = 0
        for item in by_component[component]:
            size = item["bytes"]
            if current and (len(current) >= max_files or current_bytes + size > max_bytes):
                batches.append((component, current))
                current = []
                current_bytes = 0
            current.append({
                "path": item["path"],
                "bytes": size,
                "lines": item["lines"],
                "sha256": item["sha256"],
            })
            current_bytes += size
        if current:
            batches.append((component, current))
    return [
        {
            "id": f"batch-{index:04d}",
            "component": component,
            "file_count": len(batch),
            "total_bytes": sum(item["bytes"] for item in batch),
            "files": batch,
        }
        for index, (component, batch) in enumerate(batches, start=1)
    ]


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _markdown(inventory, config):
    summary = inventory["summary"]
    lines = [
        "# Source inventory",
        "",
        "> Inventory only. Documentation generation and AI analysis are not implemented.",
        "",
        "## Scope",
        "",
        f"- Source root: `{inventory['source_root']}`",
        f"- Included extensions: {', '.join(config['source_extensions'])}",
        f"- Exclusion patterns: {', '.join(config['exclude']) or '(none)'}",
        f"- Maximum file size read: {config['max_file_bytes']} bytes",
        f"- Batch limits: {config['max_batch_files']} files / {config['max_batch_bytes']} bytes",
        "- Line counts include blank lines. Only files within the configured extensions and size limit are read.",
        "",
        "## Observed inventory",
        "",
        f"- Source files found: {summary['source_files_found']}",
        f"- Files inspected: {summary['inspected_files']}",
        f"- Lines in inspected files: {summary['inspected_lines']}",
        f"- Planned batches: {summary['batch_count']}",
        f"- Files not inspected: {summary['uninspected_files']}",
        "",
        "| Extension | Files inspected | Lines |",
        "| --- | ---: | ---: |",
    ]
    for extension, totals in sorted(inventory["by_extension"].items()):
        lines.append(f"| `{extension}` | {totals['files']} | {totals['lines']} |")
    lines.extend([
        "",
        "## Limitations",
        "",
        "- Inventory counts are limited to the configured extensions and declared exclusions.",
        "- Excluded directories are not traversed; their contents are not counted.",
        "- Oversized, binary, unreadable, or changing files are listed as uninspected.",
        "- The inventory does not establish architectural or behavioral facts.",
        "- Source revision is not collected; no source code is executed and no network is used.",
        "- Batches are separated by top-level source component and contain paths, sizes, line counts, and hashes, not source contents.",
    ])
    return "\n".join(lines) + "\n"


def run_inventory(config, repo_root, run_id=None):
    source_root = config["_source_root"]
    output_root = config["_output_root"]
    if run_id is None:
        run_id = dt.datetime.now(dt.timezone.utc).strftime("inventory-%Y%m%dT%H%M%S.%fZ")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise InventoryError("run-id must be a simple directory name")

    output_root.mkdir(parents=True, exist_ok=True)
    resolved_output = output_root.resolve()
    if not _is_within(resolved_output, repo_root) or resolved_output == repo_root:
        raise InventoryError("output_root resolves outside the agent repository")
    if _is_within(resolved_output, source_root) or _is_within(source_root, resolved_output):
        raise InventoryError("output_root and source_root must not overlap")

    run_dir = resolved_output / run_id
    run_dir.mkdir(exist_ok=False)
    started_at = _utc_now()
    entries, excluded_paths, errors, candidate_count = _scan(source_root, config)
    inspected = [item for item in entries if item["status"] == "inspected"]

    by_extension = {}
    for item in inspected:
        extension = Path(item["path"]).suffix.lower() or "(no extension)"
        totals = by_extension.setdefault(extension, {"files": 0, "lines": 0})
        totals["files"] += 1
        totals["lines"] += item["lines"]

    batches = _make_batches(
        entries,
        config["max_batch_files"],
        config["max_batch_bytes"],
    )
    uninspected = [item for item in entries if item["status"] != "inspected"]
    inventory = {
        "schema_version": 1,
        "source_root": str(source_root),
        "scope": {
            "source_extensions": config["source_extensions"],
            "exclude_patterns": config["exclude"],
            "max_file_bytes": config["max_file_bytes"],
            "max_batch_files": config["max_batch_files"],
            "max_batch_bytes": config["max_batch_bytes"],
        },
        "summary": {
            "source_files_found": candidate_count,
            "inspected_files": len(inspected),
            "inspected_lines": sum(item["lines"] for item in inspected),
            "batch_count": len(batches),
            "uninspected_files": len(uninspected),
            "excluded_paths": len(excluded_paths),
        },
        "by_extension": by_extension,
        "files": entries,
        "excluded_paths": excluded_paths,
        "batches": batches,
    }
    limitations = [
        "This run performs inventory and batch planning only; documentation generation is not implemented.",
        "No model is configured. No network access or source upload occurs.",
        "Excluded directory contents are not traversed or counted.",
        "Source revision is not collected.",
        "Batches are grouped by top-level source component before applying size and file-count limits.",
    ]
    run = {
        "schema_version": 1,
        "status": "partial",
        "source_root": str(source_root),
        "source_revision": None,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "inspected_files": [item["path"] for item in inspected],
        "errors": errors,
        "limitations": limitations,
    }

    (run_dir / "inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "inventory.md").write_text(
        _markdown(inventory, config),
        encoding="utf-8",
    )
    run["finished_at"] = _utc_now()
    (run_dir / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir

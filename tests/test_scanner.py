from pathlib import Path

import pytest

from retro_doc_agent.scanner import scan_source
from retro_doc_agent.scanner.filesystem import ScannedText


def test_scan_applies_exclusions_and_nested_gitignore_before_reading(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / ".gitignore").write_text("private.txt\nignored/\n", encoding="utf-8")
    (source / "nested" / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (source / "app.py").write_text("print('safe')\n", encoding="utf-8")
    (source / "private.txt").write_text("must not be read\n", encoding="utf-8")
    (source / "ignored").mkdir()
    (source / "ignored" / "secret.py").write_text("SECRET_VALUE", encoding="utf-8")
    (source / "nested" / "kept.py").write_text("value = 1\n", encoding="utf-8")
    (source / "nested" / "cache.tmp").write_text("ignored", encoding="utf-8")
    (source / ".env").write_text("API_KEY=never-read\n", encoding="utf-8")
    consumed: list[str] = []

    result = scan_source(
        source,
        on_text_file=lambda item: consumed.append(item.record.path),
    )

    assert "private.txt" in result.excluded_files
    assert "ignored" in result.excluded_files
    assert "nested/cache.tmp" in result.excluded_files
    assert ".env" in result.excluded_files
    assert "private.txt" not in consumed
    assert "ignored/secret.py" not in consumed
    assert ".env" not in consumed
    assert result.source_hash_complete is True
    assert [item.path for item in result.files] == sorted(item.path for item in result.files)


def test_scan_marks_oversized_file_uninspected(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text("x" * 20, encoding="utf-8")

    result = scan_source(tmp_path, max_file_bytes=10)

    assert result.files == ()
    assert result.uninspected_files[0].path == "large.py"
    assert result.uninspected_files[0].reason == "taille maximale dépassée"
    assert result.source_hash_complete is False


def test_scan_skips_symlinks_when_platform_allows(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("external", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    link = source / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Création de lien symbolique indisponible : {exc}")

    seen: list[ScannedText] = []
    result = scan_source(source, on_text_file=seen.append)

    assert "linked.txt" in result.excluded_files
    assert seen == []

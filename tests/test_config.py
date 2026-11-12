from pathlib import Path

import pytest
from typer.testing import CliRunner

from retro_doc_agent.cli import app
from retro_doc_agent.config import ConfigError, load_config


def test_load_config_resolves_relative_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "retro_doc_lab.toml"
    config_path.write_text(
        'schema_version = 1\noutput_root = "reports"\nsource_root = "source"\n',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.output_root == (tmp_path / "reports").resolve()
    assert config.source_root == (tmp_path / "source").resolve()
    assert config.llm_enabled is False


def test_invalid_config_error_does_not_echo_values(tmp_path: Path) -> None:
    config_path = tmp_path / "retro_doc_lab.toml"
    config_path.write_text('max_file_bytes = -1\n', encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        load_config(config_path)

    assert "-1" not in str(error.value)
    assert "max_file_bytes" in str(error.value)


def test_cli_lists_all_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("analyze", "characterize", "audit", "sequences", "validate"):
        assert command in result.stdout


def test_analyze_reports_pending_feature_after_validating_source(tmp_path: Path) -> None:
    config_path = tmp_path / "retro_doc_lab.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["analyze", str(tmp_path), "--config", str(config_path), "--no-llm"],
    )

    assert result.exit_code == 3
    assert "prochain lot" in result.stderr

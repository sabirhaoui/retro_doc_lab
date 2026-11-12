import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retro_doc_agent.characterization import characterize
from retro_doc_agent.cli import app
from retro_doc_agent.config import ToolConfig
from retro_doc_agent.models.characterization import Characterization


def _snapshot(source: Path) -> dict[str, str]:
    return {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }


def test_characterize_generates_evidenced_report_without_source_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "project"
    (source / "src").mkdir(parents=True)
    (source / "tests").mkdir()
    (source / ".github" / "workflows").mkdir(parents=True)
    (source / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi==0.115.0", "pytest>=8.0"]\n',
        encoding="utf-8",
    )
    (source / "src" / "app.py").write_text(
        'import os\nDATABASE_URL = os.getenv("DATABASE_URL")\n',
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        'if __name__ == "__main__":\n    print("ready")\n',
        encoding="utf-8",
    )
    (source / "tests" / "test_app.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (source / ".env.example").write_text(
        "API_TOKEN=do-not-copy-this-value\n", encoding="utf-8"
    )
    (source / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")
    (source / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\n", encoding="utf-8"
    )
    (source / "README.md").write_text("# Project\n", encoding="utf-8")
    before = _snapshot(source)
    output = tmp_path / "reports"

    run_directory = characterize(source, output, ToolConfig())

    json_path = run_directory / "characterization" / "characterization.json"
    markdown_path = run_directory / "characterization" / "characterization.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    report = Characterization.model_validate(data)
    markdown = markdown_path.read_text(encoding="utf-8")
    serialized = json_path.read_text(encoding="utf-8")
    after = _snapshot(source)

    assert before == after
    assert report.schema_version == 1
    assert {fact.name for fact in report.frameworks} == {"FastAPI"}
    assert {(item.name, item.version) for item in report.dependencies} >= {
        ("fastapi", "0.115.0"),
        ("pytest", "8.0"),
    }
    assert {fact.name for fact in report.environment_variables} == {
        "API_TOKEN",
        "DATABASE_URL",
    }
    assert "do-not-copy-this-value" not in markdown
    assert "do-not-copy-this-value" not in serialized
    facts = (
        report.frameworks
        + report.entry_points
        + report.infrastructure
        + report.data_and_services
        + report.environment_variables
        + report.tests.frameworks
        + report.tests.execution_commands
    )
    evidence = [
        item
        for fact in facts
        for item in fact.evidence
    ] + [
        item
        for dependency in report.dependencies
        for item in dependency.evidence
    ]
    assert all(
        1 <= evidence.start_line <= len((source / evidence.path).read_text().splitlines())
        for evidence in evidence
    )
    assert (run_directory / "run-manifest.json").is_file()
    assert (run_directory / "run.json").is_file()


def test_characterize_rejects_output_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()

    with pytest.raises(ValueError, match="situé dans la source"):
        characterize(source, source / "reports", ToolConfig())

    assert list(source.iterdir()) == []


def test_characterize_cli_writes_to_explicit_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
    output = tmp_path / "reports"

    result = CliRunner().invoke(
        app,
        ["characterize", str(source), "--out", str(output), "--no-llm"],
    )

    assert result.exit_code == 0
    assert "Caractérisation créée" in result.stdout
    assert len(list(output.iterdir())) == 1

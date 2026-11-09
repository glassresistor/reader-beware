"""Tests for beware.check and the `beware check` CLI command."""

import os

from click.testing import CliRunner

from beware.check import check_narrative, to_dot
from beware.cli import cli as cli_group

HERE = os.path.dirname(os.path.abspath(__file__))
NARRATIVES = os.path.join(HERE, "narratives")


def narrative(name):
    return os.path.join(NARRATIVES, name)


# ---------------------------------------------------------------------------
# Unit tests for check_narrative
# ---------------------------------------------------------------------------


def test_clean_narrative():
    text = open(narrative("check_clean.yaml")).read()
    result = check_narrative(text)

    assert result.total_sections == 3
    assert result.entrypoint == "entrypoint"
    assert not result.broken_links
    assert not result.unreachable
    # "finish" has no outgoing links -> dead end (expected for an ending)
    assert result.dead_ends == ["finish"]
    assert not result.has_errors


def test_broken_link_detected():
    text = open(narrative("check_issues.yaml")).read()
    result = check_narrative(text)

    assert "nonexistent-door" in result.broken_links
    assert "entrypoint" in result.broken_links["nonexistent-door"]


def test_unreachable_section_detected():
    text = open(narrative("check_issues.yaml")).read()
    result = check_narrative(text)

    assert "orphan-section" in result.unreachable


def test_dead_ends_detected():
    text = open(narrative("check_issues.yaml")).read()
    result = check_narrative(text)

    # "right" has no outgoing links and is not an ending prefix
    assert "right" in result.dead_ends
    # "hallway" does have outgoing links (back to left)
    assert "hallway" not in result.dead_ends


def test_missing_entrypoint():
    text = open(narrative("no_entrypoint.yaml")).read()
    result = check_narrative(text)

    assert result.entrypoint is None
    assert result.has_errors


def test_has_errors_with_issues():
    text = open(narrative("check_issues.yaml")).read()
    result = check_narrative(text)

    assert result.has_errors  # broken link + unreachable


# ---------------------------------------------------------------------------
# DOT output
# ---------------------------------------------------------------------------


def test_dot_output_contains_nodes():
    text = open(narrative("check_clean.yaml")).read()
    result = check_narrative(text)
    dot = to_dot(result)

    assert "digraph narrative" in dot
    assert '"entrypoint"' in dot
    assert '"middle"' in dot
    assert '"finish"' in dot


def test_dot_output_contains_edges():
    text = open(narrative("check_clean.yaml")).read()
    result = check_narrative(text)
    dot = to_dot(result)

    assert '"entrypoint" -> "middle"' in dot
    assert '"middle" -> "finish"' in dot


def test_dot_output_marks_broken_links():
    text = open(narrative("check_issues.yaml")).read()
    result = check_narrative(text)
    dot = to_dot(result)

    # broken target should appear as a phantom node with red styling
    assert "nonexistent-door" in dot
    assert "missing" in dot
    assert 'style=dashed, color="#dc3545"' in dot


def test_dot_output_marks_unreachable():
    text = open(narrative("check_issues.yaml")).read()
    result = check_narrative(text)
    dot = to_dot(result)

    assert "unreachable" in dot


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_check_clean(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli_group,
        ["check", "--narrative-path", narrative("check_clean.yaml")],
    )
    assert result.exit_code == 0, result.output
    assert "Sections: 3" in result.output


def test_cli_check_issues_exit_code():
    runner = CliRunner()
    result = runner.invoke(
        cli_group,
        ["check", "--narrative-path", narrative("check_issues.yaml")],
    )
    # exit code 1 because there are structural errors (broken link, unreachable)
    assert result.exit_code == 1
    assert "Broken links" in result.output
    assert "Unreachable" in result.output


def test_cli_check_dot_to_file(tmp_path):
    dot_path = str(tmp_path / "graph.dot")
    runner = CliRunner()
    result = runner.invoke(
        cli_group,
        [
            "check",
            "--narrative-path",
            narrative("check_clean.yaml"),
            "--dot-output",
            dot_path,
        ],
    )
    assert result.exit_code == 0, result.output
    assert os.path.exists(dot_path)
    content = open(dot_path).read()
    assert "digraph" in content


def test_cli_check_dot_to_stdout():
    runner = CliRunner()
    result = runner.invoke(
        cli_group,
        [
            "check",
            "--narrative-path",
            narrative("check_clean.yaml"),
            "--dot-output",
            "-",
        ],
    )
    assert result.exit_code == 0
    assert "digraph" in result.output


def test_cli_check_quiet():
    runner = CliRunner()
    result = runner.invoke(
        cli_group,
        [
            "check",
            "--narrative-path",
            narrative("check_clean.yaml"),
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    # quiet mode: no report text
    assert "Sections:" not in result.output


def test_cli_check_missing_file():
    runner = CliRunner()
    result = runner.invoke(
        cli_group,
        ["check", "--narrative-path", "/nonexistent/file.yaml"],
    )
    assert result.exit_code == 2


def test_help_lists_check():
    runner = CliRunner()
    result = runner.invoke(cli_group, ["--help"])
    assert "check" in result.output

from __future__ import annotations

from collections.abc import Iterator

import click
import pytest
from click.testing import CliRunner
from typer.main import get_command

from okfleet.cli import app

cli = get_command(app)
runner = CliRunner()


def _command_paths(
    command: click.Command,
    prefix: tuple[str, ...] = (),
) -> Iterator[tuple[str, ...]]:
    """Yield every registered command path, including groups and the root."""
    yield prefix
    if isinstance(command, click.Group):
        for name, child in sorted(command.commands.items()):
            yield from _command_paths(child, (*prefix, name))


COMMAND_PATHS = tuple(_command_paths(cli))


def _command_at(path: tuple[str, ...]) -> click.Command:
    command = cli
    for name in path:
        assert isinstance(command, click.Group)
        command = command.commands[name]
    return command


@pytest.mark.parametrize(
    "command_path",
    COMMAND_PATHS,
    ids=lambda path: "root" if not path else " ".join(path),
)
def test_every_registered_command_generates_help(command_path: tuple[str, ...]) -> None:
    result = runner.invoke(cli, [*command_path, "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "--help" in result.output


@pytest.mark.parametrize(
    "command_path",
    COMMAND_PATHS,
    ids=lambda path: "root" if not path else " ".join(path),
)
def test_every_registered_command_has_a_help_summary(command_path: tuple[str, ...]) -> None:
    assert _command_at(command_path).help


@pytest.mark.parametrize(
    ("arguments", "option"),
    [
        (["discover", "--format", "yaml"], "--format"),
        (["bundles", "list", "--format", "yaml"], "--format"),
        (["list", "unused", "--format", "yaml"], "--format"),
        (["search", "unused", "--format", "yaml"], "--format"),
        (["searches", "run", "unused", "--format", "yaml"], "--format"),
        (["status", "unused", "--format", "yaml"], "--format"),
        (["compare", "unused", "unused", "--format", "yaml"], "--format"),
        (["validate", "unused", "--format", "yaml"], "--format"),
        (["health", "unused", "--format", "yaml"], "--format"),
        (["doctor", "--format", "yaml"], "--format"),
        (["links", "unused:concept", "--direction", "sideways"], "--direction"),
        (["graph", "unused", "--format", "yaml"], "--format"),
        (["chat", "question", "--mode", "edit"], "--mode"),
        (["chat", "question", "--provider", "other"], "--provider"),
    ],
    ids=[
        "discover-format",
        "bundles-list-format",
        "list-format",
        "search-format",
        "saved-search-format",
        "status-format",
        "compare-format",
        "validate-format",
        "health-format",
        "doctor-format",
        "links-direction",
        "graph-format",
        "chat-mode",
        "chat-provider",
    ],
)
def test_invalid_choice_values_fail_during_parsing(
    arguments: list[str],
    option: str,
) -> None:
    result = runner.invoke(cli, arguments)

    assert result.exit_code == 2, result.output
    assert "Invalid value" in result.output
    assert option in result.output
    assert "Traceback" not in result.output

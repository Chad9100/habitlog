"""Shell completion scripts generated from the parser."""

from __future__ import annotations

from datetime import date

import pytest

from habitlog import completion
from habitlog.cli import build_parser, main

TODAY = date(2026, 3, 4)


def run(capsys, *argv):
    try:
        code = main(list(argv), today=TODAY)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return code, out, err


def test_collect_finds_commands_options_and_choices():
    glob, commands, choices = completion.collect(build_parser())
    assert "--profile" in glob and "--db" in glob
    assert {"add", "done", "sync", "completion"} <= set(commands)
    assert "--dry-run" in commands["sync"] and "--prefer" in commands["sync"]
    assert choices["--prefer"] == ["local", "file"]
    assert "weekly" in choices["--every"]
    assert "never" in choices["--color"]


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_every_shell_mentions_every_command(capsys, shell):
    code, out, err = run(capsys, "completion", shell)
    assert code == 0 and err == ""
    _, commands, _ = completion.collect(build_parser())
    for name in commands:
        assert name in out
    assert "habitlog" in out


def test_bash_script_shape(capsys):
    _, out, _ = run(capsys, "completion", "bash")
    assert "complete -o default -F _habitlog habitlog" in out
    assert "--format) COMPREPLY" in out


def test_zsh_script_loads_bash_compat(capsys):
    _, out, _ = run(capsys, "completion", "zsh")
    assert "bashcompinit" in out
    assert "complete -o default -F _habitlog habitlog" in out
    assert out.count("# zsh completion") == 1


def test_powershell_script_registers_completer(capsys):
    _, out, _ = run(capsys, "completion", "powershell")
    assert "Register-ArgumentCompleter -Native -CommandName habitlog" in out
    assert "'--prefer' = @('local', 'file')" in out


def test_unknown_shell_is_a_usage_error(capsys):
    code, _, err = run(capsys, "completion", "fish")
    assert code == 2
    assert "invalid choice" in err


def test_completion_needs_no_database(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HABITLOG_DB", str(tmp_path / "missing" / "dir" / "x.db"))
    code, out, _ = run(capsys, "completion", "bash")
    assert code == 0 and out
    assert not (tmp_path / "missing").exists()

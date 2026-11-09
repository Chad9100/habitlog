from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from habitlog.cli import main

# A fixed "today" for CLI tests: Wednesday 4 March 2026.
TODAY = date(2026, 3, 4)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Never let a test fall back to the user's real database."""
    monkeypatch.setenv("HABITLOG_DB", str(tmp_path / "env-default.db"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))


@dataclass
class Result:
    code: int
    out: str
    err: str

    def json(self):
        return json.loads(self.out)


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "data" / "habits.db"


@pytest.fixture
def run(db_path, capsys):
    """Run the CLI against the temp database and capture exit code and output."""

    def _run(*argv: str, today: date = TODAY) -> Result:
        try:
            code = main(["--db", str(db_path), *argv], today=today)
        except SystemExit as exc:  # argparse usage errors
            code = exc.code if isinstance(exc.code, int) else 1
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return _run

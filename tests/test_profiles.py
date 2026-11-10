"""Profiles: --profile / HABITLOG_PROFILE map to separate database files."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from habitlog import db
from habitlog.cli import main
from habitlog.db import HabitlogError

TODAY = date(2026, 3, 4)


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    """A clean per-user data folder on every OS, with no HABITLOG_* overrides."""
    home = tmp_path / "home"
    monkeypatch.setenv("APPDATA", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.delenv("HABITLOG_DB", raising=False)
    monkeypatch.delenv("HABITLOG_PROFILE", raising=False)
    return home / "habitlog"


def cli(capsys, *argv):
    try:
        code = main(list(argv), today=TODAY)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    out, err = capsys.readouterr()
    return code, out, err


def test_profile_paths_live_next_to_the_default_database():
    env = {"XDG_DATA_HOME": "/data"}
    assert db.profile_db_path("work", env, "linux") == Path("/data/habitlog/profiles/work.db")
    assert db.profile_db_path("Work", env, "linux") == Path("/data/habitlog/profiles/work.db")
    assert db.profile_db_path("default", env, "linux") == db.default_db_path(env, "linux")


@pytest.mark.parametrize("name", ["", "../x", "a/b", "a b", "-x", "x" * 41, "work.db"])
def test_unsafe_profile_names_are_rejected(name):
    with pytest.raises(HabitlogError, match="invalid profile name"):
        db.check_profile_name(name)


def test_choose_db_order(tmp_path):
    env = {
        "XDG_DATA_HOME": str(tmp_path), "APPDATA": str(tmp_path),
        "HABITLOG_DB": str(tmp_path / "env.db"), "HABITLOG_PROFILE": "home",
    }
    assert db.choose_db("cli.db", None, env).source == "--db"
    c = db.choose_db(None, "Work", env)
    assert (c.profile, c.source, c.path.name) == ("work", "--profile", "work.db")
    c = db.choose_db(None, None, env)
    assert (c.profile, c.source, c.path) == (None, "HABITLOG_DB", tmp_path / "env.db")
    env["HABITLOG_DB"] = ""
    c = db.choose_db(None, None, env)
    assert (c.profile, c.source, c.path.name) == ("home", "HABITLOG_PROFILE", "home.db")
    del env["HABITLOG_PROFILE"]
    assert db.choose_db(None, None, env).source == "default"
    with pytest.raises(HabitlogError, match="not both"):
        db.choose_db("cli.db", "work", env)


def test_profiles_keep_habits_separate(data_home, capsys, monkeypatch):
    assert cli(capsys, "--profile", "work", "add", "Standup")[0] == 0
    assert cli(capsys, "add", "Read", "--profile", "work")[0] == 0  # after the command too
    assert cli(capsys, "add", "Walk")[0] == 0
    assert (data_home / "profiles" / "work.db").is_file()
    assert (data_home / "habitlog.db").is_file()

    code, out, _ = cli(capsys, "list", "--json")
    assert [h["name"] for h in json.loads(out)] == ["Walk"]
    monkeypatch.setenv("HABITLOG_PROFILE", "work")
    code, out, _ = cli(capsys, "list", "--json")
    assert [h["name"] for h in json.loads(out)] == ["Read", "Standup"]
    # --profile beats the environment variable.
    code, out, _ = cli(capsys, "--profile", "default", "list", "--json")
    assert [h["name"] for h in json.loads(out)] == ["Walk"]


def test_profiles_command_lists_and_marks_active(data_home, capsys, monkeypatch):
    cli(capsys, "--profile", "work", "add", "Standup")
    cli(capsys, "--profile", "work", "add", "Inbox")
    cli(capsys, "--profile", "home", "add", "Dishes")
    code, out, _ = cli(capsys, "--profile", "work", "profiles")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["PROFILE", "HABITS", "DATABASE"]
    rows = [line.split()[:3] for line in lines[1:4]]
    assert rows[0][:2] == ["default", "0"] and "(not created yet)" in lines[1]
    assert rows[1] == ["home", "1", str(data_home / "profiles" / "home.db")]
    assert rows[2] == ["*", "work", "2"]
    assert "chosen by --profile" in out
    # Listing profiles never creates the default database.
    assert not (data_home / "habitlog.db").exists()

    monkeypatch.setenv("HABITLOG_PROFILE", "home")
    code, out, _ = cli(capsys, "profiles", "--json")
    data = json.loads(out)
    assert (data["active"], data["source"]) == ("home", "HABITLOG_PROFILE")
    assert [p["name"] for p in data["profiles"]] == ["default", "home", "work"]
    assert [p["active"] for p in data["profiles"]] == [False, True, False]
    assert data["profiles"][0]["exists"] is False


def test_profiles_with_explicit_db_file(data_home, tmp_path, capsys):
    other = tmp_path / "other.db"
    code, out, _ = cli(capsys, "--db", str(other), "profiles")
    assert code == 0
    assert "*" not in out
    assert f"Using {other} from --db, not a profile." in out


def test_bad_profile_name_and_conflicting_options_are_errors(data_home, capsys, monkeypatch):
    code, _, err = cli(capsys, "--profile", "../evil", "list")
    assert code == 1 and "invalid profile name" in err
    code, _, err = cli(capsys, "--profile", "a", "--db", "x.db", "list")
    assert code == 1 and "not both" in err
    monkeypatch.setenv("HABITLOG_PROFILE", "no/slashes")
    code, _, err = cli(capsys, "profiles")
    assert code == 1 and "invalid profile name" in err
    assert not data_home.exists()

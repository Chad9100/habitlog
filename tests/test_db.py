from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from habitlog import db

DAY = date(2026, 3, 4)


def test_resolve_prefers_cli_then_env_then_default(tmp_path):
    env = {"HABITLOG_DB": str(tmp_path / "env.db"), "APPDATA": str(tmp_path)}
    assert db.resolve_db_path(str(tmp_path / "cli.db"), env) == tmp_path / "cli.db"
    assert db.resolve_db_path(None, env) == tmp_path / "env.db"
    assert db.resolve_db_path(None, {"HABITLOG_DB": ""}).name == "habitlog.db"


def test_default_path_windows_uses_appdata():
    p = db.default_db_path({"APPDATA": r"C:\Users\x\AppData\Roaming"}, "win32")
    assert p == Path(r"C:\Users\x\AppData\Roaming") / "habitlog" / "habitlog.db"


def test_default_path_posix_uses_xdg_then_local_share():
    assert db.default_db_path({"XDG_DATA_HOME": "/data"}, "linux") == Path("/data/habitlog/habitlog.db")
    fallback = db.default_db_path({}, "linux")
    assert fallback == Path.home() / ".local" / "share" / "habitlog" / "habitlog.db"


def test_connect_creates_parent_dirs_and_schema(tmp_path):
    path = tmp_path / "a" / "b" / "h.db"
    conn = db.connect(path)
    try:
        assert path.exists()
        assert db.get_schema_version(conn) == db.SCHEMA_VERSION
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"meta", "habits", "completions"} <= tables
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "h.db")
    try:
        assert db.migrate(conn) == db.SCHEMA_VERSION
        assert db.migrate(conn) == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_migrate_from_empty_database(tmp_path):
    raw = sqlite3.connect(str(tmp_path / "old.db"), isolation_level=None)
    raw.row_factory = sqlite3.Row
    try:
        assert db.get_schema_version(raw) == 0
        assert db.migrate(raw) == 1
    finally:
        raw.close()


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "h.db"
    conn = db.connect(path)
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.close()
    with pytest.raises(db.HabitlogError, match="newer"):
        db.connect(path)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "h.db")
    yield c
    c.close()


def test_names_are_case_insensitive_unique(conn):
    db.add_habit(conn, "Read", "daily", 1, DAY)
    with pytest.raises(db.HabitlogError, match="already exists"):
        db.add_habit(conn, "  READ ", "daily", 1, DAY)
    assert db.get_habit(conn, "read").name == "Read"


def test_rename_to_different_case_of_same_habit(conn):
    db.add_habit(conn, "read", "daily", 1, DAY)
    assert db.rename_habit(conn, "read", "Read").name == "Read"


def test_remove_cascades_completions(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, DAY, 2)
    assert db.remove_habit(conn, h) == 1
    assert conn.execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 0


def test_undo_removes_latest_row_only(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, DAY, 1)
    db.add_completion(conn, h, DAY, 3)
    assert db.undo_completion(conn, h, DAY) == 3
    assert db.completion_counts(conn, h) == {DAY: 1}


def test_failed_import_rolls_back(conn):
    data = {
        "habits": [
            {"name": "Ok", "completions": [{"date": "2026-03-01", "count": 1}]},
            {"name": "Bad", "completions": [{"date": "nope", "count": 1}]},
        ]
    }
    with pytest.raises(db.HabitlogError):
        db.import_data(conn, data, DAY)
    assert db.list_habits(conn, include_archived=True) == []

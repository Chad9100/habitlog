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
        assert db.migrate(raw) == db.SCHEMA_VERSION
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


def test_migration_2_keeps_v1_data_and_adds_notes(tmp_path):
    """A database created by habitlog 0.1 (schema 1) upgrades in place."""
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(str(path), isolation_level=None)
    raw.row_factory = sqlite3.Row
    assert db.migrate(raw, target_version=1) == 1
    raw.execute(
        "INSERT INTO habits (name, name_key, every, target, archived, created) "
        "VALUES ('Read', 'read', 'daily', 1, 0, '2026-03-01')"
    )
    raw.execute(
        "INSERT INTO completions (habit_id, day, count, logged_at) "
        "VALUES (1, '2026-03-02', 2, '2026-03-02T08:00:00')"
    )
    raw.close()

    conn = db.connect(path)
    try:
        assert db.get_schema_version(conn) == db.SCHEMA_VERSION
        h = db.get_habit(conn, "read")
        assert db.completion_counts(conn, h) == {date(2026, 3, 2): 2}
        assert db.completion_notes(conn, h) == []
        db.add_completion(conn, h, DAY, 1, "chapter 4")
        assert db.completion_notes(conn, h) == [(DAY, "chapter 4")]
    finally:
        conn.close()


def test_notes_are_cleaned_and_validated(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, DAY, 1, "  two\n lines\tand   spaces ")
    assert db.completion_notes(conn, h) == [(DAY, "two lines and spaces")]
    with pytest.raises(db.HabitlogError, match="empty"):
        db.add_completion(conn, h, DAY, 1, "   ")
    with pytest.raises(db.HabitlogError, match="longer than"):
        db.add_completion(conn, h, DAY, 1, "x" * (db.MAX_NOTE_LENGTH + 1))
    assert db.completion_counts(conn, h) == {DAY: 1}


def test_completion_notes_date_window_and_order(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, date(2026, 3, 3), 1, "b")
    db.add_completion(conn, h, date(2026, 3, 1), 1, "a")
    db.add_completion(conn, h, date(2026, 3, 3), 1)
    db.add_completion(conn, h, date(2026, 3, 3), 1, "c")
    assert [n for _, n in db.completion_notes(conn, h)] == ["a", "b", "c"]
    assert [n for _, n in db.completion_notes(conn, h, start=date(2026, 3, 2))] == ["b", "c"]
    assert [n for _, n in db.completion_notes(conn, h, end=date(2026, 3, 2))] == ["a"]


def test_completion_log_newest_first_with_since_and_limit(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    other = db.add_habit(conn, "Gym", "weekly", 3, DAY)
    db.add_completion(conn, h, date(2026, 3, 3), 1, "b")
    db.add_completion(conn, h, date(2026, 3, 1), 2)
    db.add_completion(conn, h, date(2026, 3, 3), 1, "c")
    db.add_completion(conn, other, date(2026, 3, 3), 1, "not mine")
    entries, total = db.completion_log(conn, h)
    assert total == 3
    assert [(e.day.day, e.count, e.note) for e in entries] == [(3, 1, "c"), (3, 1, "b"), (1, 2, None)]
    assert all(e.logged_at for e in entries)
    entries, total = db.completion_log(conn, h, limit=1)
    assert total == 3 and [e.note for e in entries] == ["c"]
    entries, total = db.completion_log(conn, h, since=date(2026, 3, 2))
    assert total == 2 and [e.note for e in entries] == ["c", "b"]
    assert db.completion_log(conn, h, since=date(2026, 3, 4)) == ([], 0)


def test_undo_removes_the_note_with_its_completion(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, DAY, 1, "kept")
    db.add_completion(conn, h, DAY, 1, "undone")
    db.undo_completion(conn, h, DAY)
    assert db.completion_notes(conn, h) == [(DAY, "kept")]


def _export(name, completions):
    return {"habits": [{"name": name, "completions": completions}]}


def test_import_attaches_notes_to_existing_completions(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, DAY, 1)
    data = _export("Read", [{"date": DAY.isoformat(), "count": 1, "notes": ["ch 4"]}])
    r = db.import_data(conn, data, DAY)
    assert (r.completions_added, r.notes_added, r.notes_skipped) == (0, 1, 0)
    assert db.completion_notes(conn, h) == [(DAY, "ch 4")]
    assert db.completion_counts(conn, h) == {DAY: 1}
    again = db.import_data(conn, data, DAY)
    assert (again.completions_added, again.notes_added, again.notes_skipped) == (0, 0, 0)


def test_import_splits_new_completions_to_carry_each_note(conn):
    data = _export("Water", [{"date": DAY.isoformat(), "count": 5, "notes": ["am", "pm", "am"]}])
    r = db.import_data(conn, data, DAY)
    assert (r.completions_added, r.notes_added) == (5, 3)
    h = db.get_habit(conn, "water")
    assert db.completion_counts(conn, h) == {DAY: 5}
    assert [n for _, n in db.completion_notes(conn, h)] == ["am", "pm", "am"]
    assert db.import_data(conn, data, DAY).notes_added == 0
    assert db.completion_counts(conn, h) == {DAY: 5}


def test_import_skips_note_when_day_has_no_free_completion(conn):
    h = db.add_habit(conn, "Read", "daily", 1, DAY)
    db.add_completion(conn, h, DAY, 1, "mine")
    data = _export("Read", [{"date": DAY.isoformat(), "count": 1, "notes": ["theirs"]}])
    r = db.import_data(conn, data, DAY)
    assert (r.completions_added, r.notes_added, r.notes_skipped) == (0, 0, 1)
    assert db.completion_notes(conn, h) == [(DAY, "mine")]


@pytest.mark.parametrize(
    "notes, message",
    [("ch 4", "list of strings"), ([1], "list of strings"), (["a", "b"], "more notes"), ([" "], "empty")],
)
def test_import_rejects_bad_notes(conn, notes, message):
    data = _export("Read", [{"date": DAY.isoformat(), "count": 1, "notes": notes}])
    with pytest.raises(db.HabitlogError, match=message):
        db.import_data(conn, data, DAY)
    assert db.list_habits(conn, include_archived=True) == []

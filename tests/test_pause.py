"""Pausing a habit for a date range (vacation) without breaking its streak."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from habitlog import db, streaks
from habitlog.cli import EXIT_DUE

# The `run` fixture uses Wednesday 2026-03-04 as today.
TODAY = date(2026, 3, 4)


def _days(first: date, last: date) -> set[date]:
    return {first + timedelta(days=i) for i in range((last - first).days + 1)}


# --------------------------------------------------------------------------- streaks


def test_paused_days_bridge_a_daily_streak():
    counts = {d: 1 for d in _days(date(2026, 2, 24), date(2026, 2, 27))}
    counts[date(2026, 3, 3)] = 1
    paused = _days(date(2026, 2, 28), date(2026, 3, 2))
    assert streaks.current_streak(counts, "daily", 1, TODAY) == 1
    # Paused days are skipped: they neither break nor extend the streak.
    assert streaks.current_streak(counts, "daily", 1, TODAY, paused) == 5
    assert streaks.longest_streak(counts, "daily", 1, TODAY) == 4
    assert streaks.longest_streak(counts, "daily", 1, TODAY, paused) == 5


def test_completions_on_paused_days_still_count():
    counts = {d: 1 for d in _days(date(2026, 2, 28), date(2026, 3, 3))}
    paused = _days(date(2026, 3, 1), date(2026, 3, 2))
    assert streaks.current_streak(counts, "daily", 1, TODAY, paused) == 4


def test_a_pause_does_not_cover_unpaused_misses():
    counts = {date(2026, 2, 26): 1, date(2026, 3, 3): 1}
    paused = {date(2026, 2, 28), date(2026, 3, 1), date(2026, 3, 2)}  # 2026-02-27 missed
    assert streaks.current_streak(counts, "daily", 1, TODAY, paused) == 1
    assert streaks.longest_streak(counts, "daily", 1, TODAY, paused) == 1


def test_weekly_period_is_paused_when_any_of_its_days_is():
    counts = {date(2026, 2, 16): 2, date(2026, 2, 24): 1}  # week of 02-23 short of 2
    assert streaks.current_streak(counts, "weekly", 2, TODAY) == 0
    paused = {date(2026, 2, 27)}
    assert streaks.current_streak(counts, "weekly", 2, TODAY, paused) == 1
    rate = streaks.rate_between(counts, "weekly", 2, date(2026, 2, 16), TODAY, TODAY, paused)
    assert (rate.periods_met, rate.periods_total) == (1, 1)


def test_weekday_habit_ignores_paused_weekends():
    # Fri 02-27 and Mon 03-02 done; the weekend in between is no period anyway.
    counts = {date(2026, 2, 27): 1, date(2026, 3, 2): 1, date(2026, 3, 3): 1}
    paused = {date(2026, 2, 28), date(2026, 3, 1)}
    assert streaks.current_streak(counts, "weekdays", 1, TODAY, paused) == 3
    assert streaks.current_streak(counts, "weekdays", 1, TODAY) == 3


def test_unmet_paused_periods_are_left_out_of_rates():
    counts = {date(2026, 3, 1): 1, date(2026, 3, 3): 1}
    paused = {date(2026, 3, 2), date(2026, 3, 3)}
    rate = streaks.rate_between(counts, "daily", 1, date(2026, 3, 1), TODAY, TODAY, paused)
    # 03-02 paused and missed: dropped. 03-03 paused but done: met. Today open.
    assert (rate.periods_met, rate.periods_total) == (2, 2)


def test_today_progress_reports_paused_until_met():
    paused = {TODAY}
    assert streaks.today_progress({}, "daily", 1, TODAY, paused).status == "paused"
    assert streaks.today_progress({TODAY: 1}, "daily", 1, TODAY, paused).status == "done"
    assert streaks.today_progress({}, "daily", 1, TODAY).status == "open"


# --------------------------------------------------------------------------- db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


def test_overlapping_and_adjacent_pauses_merge(conn):
    h = db.add_habit(conn, "Read", "daily", 1, date(2026, 1, 1))
    db.add_pause(conn, h, date(2026, 3, 10), date(2026, 3, 12))
    db.add_pause(conn, h, date(2026, 3, 20), date(2026, 3, 21))
    merged = db.add_pause(conn, h, date(2026, 3, 13), date(2026, 3, 20))  # adjacent + overlap
    assert merged == db.Pause(date(2026, 3, 10), date(2026, 3, 21))
    assert db.list_pauses(conn, h) == [merged]
    assert db.paused_days(conn, h) == frozenset(_days(date(2026, 3, 10), date(2026, 3, 21)))


def test_pause_validation(conn):
    h = db.add_habit(conn, "Read", "daily", 1, date(2026, 1, 1))
    with pytest.raises(db.HabitlogError, match="before it starts"):
        db.add_pause(conn, h, date(2026, 3, 10), date(2026, 3, 9))
    with pytest.raises(db.HabitlogError, match="at most 366 days"):
        db.add_pause(conn, h, date(2026, 1, 1), date(2027, 1, 2))
    assert db.list_pauses(conn, h) == []


def test_end_pause_cuts_short_or_removes(conn):
    h = db.add_habit(conn, "Read", "daily", 1, date(2026, 1, 1))
    db.add_pause(conn, h, date(2026, 3, 1), date(2026, 3, 10))
    db.add_pause(conn, h, date(2026, 4, 1), date(2026, 4, 3))
    assert db.end_pause(conn, h, date(2026, 3, 5)) == db.Pause(date(2026, 3, 1), date(2026, 3, 10))
    assert db.list_pauses(conn, h)[0] == db.Pause(date(2026, 3, 1), date(2026, 3, 4))
    # Nothing contains 03-20, so the next pause (April) is removed.
    assert db.end_pause(conn, h, date(2026, 3, 20)).first == date(2026, 4, 1)
    assert len(db.list_pauses(conn, h)) == 1
    assert db.end_pause(conn, h, date(2026, 5, 1)) is None
    assert db.clear_pauses(conn, h) == 1


def test_removing_a_habit_removes_its_pauses(conn):
    h = db.add_habit(conn, "Read", "daily", 1, date(2026, 1, 1))
    db.add_pause(conn, h, date(2026, 3, 1), date(2026, 3, 2))
    db.remove_habit(conn, h)
    assert conn.execute("SELECT COUNT(*) FROM pauses").fetchone()[0] == 0


def test_migration_3_upgrades_a_v2_database(tmp_path):
    path = tmp_path / "v2.db"
    raw = sqlite3.connect(str(path), isolation_level=None)
    raw.row_factory = sqlite3.Row
    assert db.migrate(raw, target_version=2) == 2
    raw.execute(
        "INSERT INTO habits (name, name_key, every, target, archived, created) "
        "VALUES ('Read', 'read', 'daily', 1, 0, '2026-03-01')"
    )
    raw.close()
    conn = db.connect(path)
    try:
        assert db.get_schema_version(conn) == 3
        h = db.get_habit(conn, "Read")
        assert db.list_pauses(conn, h) == []
        db.add_pause(conn, h, date(2026, 3, 2), date(2026, 3, 3))
        assert len(db.paused_days(conn, h)) == 2
    finally:
        conn.close()


# --------------------------------------------------------------------------- cli


def _streak(run, name="Read"):
    return next(h for h in run("list", "--json").json() if h["name"] == name)


def test_pause_keeps_the_streak_through_a_vacation(run):
    assert run("add", "Read").code == 0
    for d in ("2026-02-25", "2026-02-26"):
        assert run("done", "Read", "--date", d).code == 0
    r = run("pause", "Read", "--from", "2026-02-27", "--to", "2026-03-02")
    assert r.code == 0, r.err
    assert "Paused 'Read' from 2026-02-27 to 2026-03-02 (4 days)." in r.out
    assert run("done", "Read", "--date", "2026-03-03").code == 0
    s = _streak(run)
    assert (s["current_streak"], s["longest_streak"]) == (3, 3)
    stats = run("stats", "Read", "--weeks", "2", "--json").json()
    assert stats["pauses"] == [{"from": "2026-02-27", "to": "2026-03-02", "days": 4}]
    assert (stats["periods_met"], stats["periods_total"]) == (3, 3)
    assert "Paused: 2026-02-27 to 2026-03-02 (4 days)" in run("stats", "Read", "--ascii").out


def test_paused_habit_is_not_due_and_shows_paused(run):
    assert run("add", "Read").code == 0
    assert run("add", "Gym", "--every", "weekly", "--target", "3").code == 0
    assert run("due").code == EXIT_DUE
    assert run("pause", "Read", "--days", "3").code == 0  # 03-04 to 03-06
    assert run("pause", "Gym", "--from", "2026-03-07", "--days", "1").code == 0  # Saturday
    r = run("due", "--json")
    assert r.code == 0 and r.json()["due"] == []
    assert _streak(run)["today"]["status"] == "paused"
    line = next(x for x in run("list").out.splitlines() if x.startswith("Read"))
    assert "paused" in line
    # Logging anyway still counts.
    assert run("done", "Read").code == 0
    assert _streak(run)["today"]["status"] == "done"


def test_pause_list_and_unpause(run):
    assert run("add", "Read").code == 0
    assert run("pause", "Read", "--list").out.strip() == "'Read' has no pauses."
    assert run("pause", "Read", "--from", "2026-03-01", "--to", "2026-03-10").code == 0
    assert run("pause", "Read", "--from", "2026-04-01", "--days", "1").code == 0
    out = run("pause", "Read", "--list").out
    assert "2026-03-01 to 2026-03-10 (10 days) (now)" in out
    assert "2026-04-01 (1 day)" in out
    r = run("unpause", "Read")
    assert r.code == 0 and "it now ends 2026-03-03" in r.out
    data = run("pause", "Read", "--list", "--json").json()
    assert data["pauses"][0] == {"from": "2026-03-01", "to": "2026-03-03", "days": 3}
    r = run("unpause", "Read")
    assert "Removed the pause of 'Read': 2026-04-01 (1 day)." in r.out
    r = run("unpause", "Read")
    assert r.code == 1 and "no pause on or after 2026-03-04" in r.err
    assert run("unpause", "Read", "--all").out.strip() == "Removed 1 pause of 'Read'."


def test_pause_errors(run):
    assert run("add", "Read").code == 0
    r = run("pause", "Read")
    assert r.code == 1 and "--to DATE, --days N" in r.err
    assert run("pause", "Read", "--to", "2026-03-10", "--days", "2").code == 2
    r = run("pause", "Read", "--to", "2026-03-01")
    assert r.code == 1 and "before it starts" in r.err
    assert run("pause", "Read", "--list", "--from", "2026-03-01").code == 1
    assert run("archive", "Read").code == 0
    r = run("pause", "Read", "--days", "2")
    assert r.code == 1 and "archived" in r.err
    assert run("pause", "Nope", "--days", "2").code == 1


def test_due_says_when_habits_are_paused_rather_than_done(run):
    assert run("add", "Read").code == 0
    assert run("add", "Gym").code == 0
    assert run("pause", "Read", "--days", "2").code == 0
    assert run("pause", "Gym", "--days", "2").code == 0
    r = run("due")
    assert r.code == 0
    assert r.out.strip() == "Nothing due on 2026-03-04: every habit is paused."
    assert run("due", "--json").json()["paused"] == 2
    assert run("done", "Gym").code == 0  # met anyway: no longer counted as paused
    assert run("due").out.strip() == "All done for 2026-03-04 (1 habit paused)."
    assert run("unpause", "Read").code == 0
    assert run("done", "Read").code == 0
    assert run("due").out.strip() == "All done for 2026-03-04."
    assert run("due", "--json").json()["paused"] == 0


# --------------------------------------------------------------------------- export / import


def test_export_includes_pauses_only_when_there_are_some(conn):
    read = db.add_habit(conn, "Read", "daily", 1, date(2026, 1, 1))
    db.add_habit(conn, "Gym", "weekly", 2, date(2026, 1, 1))
    db.add_pause(conn, read, date(2026, 2, 1), date(2026, 2, 3))
    db.add_pause(conn, read, date(2026, 4, 1), date(2026, 4, 1))  # future pauses too
    habits = {h["name"]: h for h in db.export_data(conn)["habits"]}
    assert habits["Read"]["pauses"] == [
        {"from": "2026-02-01", "to": "2026-02-03"},
        {"from": "2026-04-01", "to": "2026-04-01"},
    ]
    assert "pauses" not in habits["Gym"]


def test_pauses_round_trip_and_reimport_is_idempotent(conn):
    src = db.connect(":memory:")
    try:
        h = db.add_habit(src, "Read", "daily", 1, date(2026, 1, 1))
        db.add_completion(src, h, date(2026, 2, 5))
        db.add_pause(src, h, date(2026, 2, 1), date(2026, 2, 3))
        db.add_pause(src, h, date(2026, 3, 10), date(2026, 3, 20))
        data = db.export_data(src)
    finally:
        src.close()
    first = db.import_data(conn, data, TODAY)
    assert (first.habits_created, first.pauses_added) == (1, 2)
    read = db.get_habit(conn, "Read")
    assert db.list_pauses(conn, read) == [
        db.Pause(date(2026, 2, 1), date(2026, 2, 3)),
        db.Pause(date(2026, 3, 10), date(2026, 3, 20)),
    ]
    again = db.import_data(conn, data, TODAY)
    assert (again.habits_existing, again.completions_added, again.pauses_added) == (1, 0, 0)
    assert len(db.list_pauses(conn, read)) == 2


def test_imported_pauses_merge_with_existing_ones(conn):
    h = db.add_habit(conn, "Read", "daily", 1, date(2026, 1, 1))
    db.add_pause(conn, h, date(2026, 2, 1), date(2026, 2, 5))
    data = {
        "habits": [
            {
                "name": "read",
                "pauses": [
                    {"from": "2026-02-02", "to": "2026-02-04"},  # already covered
                    {"from": "2026-02-06", "to": "2026-02-08"},  # adjacent: joins
                ],
            }
        ]
    }
    result = db.import_data(conn, data, TODAY)
    assert result.pauses_added == 1
    assert db.list_pauses(conn, h) == [db.Pause(date(2026, 2, 1), date(2026, 2, 8))]


def test_old_exports_without_pauses_still_import(conn):
    data = {
        "format": "habitlog-export",
        "version": 1,
        "habits": [{"name": "Read", "completions": [{"date": "2026-03-01", "count": 1}]}],
    }
    result = db.import_data(conn, data, TODAY)
    assert (result.habits_created, result.completions_added, result.pauses_added) == (1, 1, 0)
    assert db.list_pauses(conn, db.get_habit(conn, "Read")) == []


@pytest.mark.parametrize(
    "pauses, message",
    [
        ([{"from": "2026-03-01"}], "habits[0].pauses[0]: invalid date None"),
        ("2026-03-01", "pauses must be a list"),
        (["2026-03-01"], "expected an object with 'from' and 'to'"),
        ([{"from": "2026-03-05", "to": "2026-03-01"}], "before it starts"),
        ([{"from": "2026-03-01", "to": "nope"}], "habits[0].pauses[0]"),
        ([{"from": "2026-01-01", "to": "2027-06-01"}], "at most 366 days"),
    ],
)
def test_bad_pauses_in_an_import_are_rejected(conn, pauses, message):
    data = {"habits": [{"name": "Read", "pauses": pauses}]}
    with pytest.raises(db.HabitlogError, match=message.replace("[", r"\[").replace("]", r"\]")):
        db.import_data(conn, data, TODAY)
    assert db.list_habits(conn, include_archived=True) == []  # nothing half-imported


def test_import_reports_added_pauses(run, tmp_path):
    path = tmp_path / "backup.json"
    path.write_text(
        '{"habits": [{"name": "Read", "pauses": [{"from": "2026-03-02", "to": "2026-03-06"}]}]}',
        encoding="utf-8",
    )
    r = run("import", str(path))
    assert r.code == 0, r.err
    assert r.out.strip() == (
        "Imported: 1 new habit, 0 already present, 0 completions added, 1 pause added."
    )
    assert "1 pause added" not in run("import", str(path)).out
    assert run("due").out.strip() == "Nothing due on 2026-03-04: every habit is paused."

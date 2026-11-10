"""`habitlog edit NAME --every/--target`."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from habitlog import db

# The `run` fixture uses Wednesday 2026-03-04 as today.
WEEK_DAYS = [date(2026, 2, 25) + timedelta(days=i) for i in range(8)]  # Wed 25 Feb .. Wed 4 Mar


@pytest.fixture
def read_habit(run):
    """A daily habit done every day from Wed 25 Feb up to and including today."""
    assert run("add", "Read").code == 0
    for d in WEEK_DAYS:
        assert run("done", "Read", "--date", d.isoformat()).code == 0
    return run


def _listed(run, name="Read"):
    return next(h for h in run("list", "--all", "--json").json() if h["name"] == name)


def test_edit_to_weekly_recalculates_whole_history(read_habit):
    run = read_habit
    assert _listed(run)["current_streak"] == 8
    r = run("edit", "read", "--every", "weekly", "--target", "3")
    assert r.code == 0, r.err
    assert "Changed 'Read' from daily, 1 time per day to weekly, 3 times per week." in r.out
    assert "8 days" in r.out and "2 weeks" in r.out
    h = _listed(run)
    assert (h["every"], h["target"], h["streak_unit"]) == ("weekly", 3, "week")
    # Week of 23 Feb has 5 completions, the current week 3: both met.
    assert h["current_streak"] == 2 and h["longest_streak"] == 2


def test_raising_target_can_break_past_streaks(read_habit):
    run = read_habit
    data = run("edit", "Read", "--target", "2", "--json").json()
    assert data["changed"] is True and data["dry_run"] is False
    assert data["before"]["current_streak"] == 8
    assert data["after"] == {
        "every": "daily", "target": 2, "current_streak": 0,
        "longest_streak": 0, "streak_unit": "day",
    }
    assert _listed(run)["target"] == 2


def test_edit_is_reversible_because_completions_are_untouched(read_habit):
    run = read_habit
    run("edit", "Read", "--target", "5")
    assert _listed(run)["longest_streak"] == 0
    run("edit", "Read", "--target", "1")
    h = _listed(run)
    assert h["current_streak"] == 8 and h["longest_streak"] == 8
    assert run("stats", "Read", "--json").json()["total_completions"] == 8


def test_switch_to_weekdays_reports_ignored_weekend_completions(read_habit):
    run = read_habit
    r = run("edit", "Read", "--every", "weekdays")
    assert r.code == 0
    # Sat 28 Feb and Sun 1 Mar stop counting; weekends don't break the streak.
    assert "2 completions on weekends no longer count towards streaks." in r.out
    assert _listed(run)["current_streak"] == 6
    # Already a weekdays habit: changing the target must not repeat the warning.
    r = run("edit", "Read", "--target", "1", "--every", "weekdays", "--json")
    assert r.json()["weekend_completions_ignored"] == 0


def test_dry_run_saves_nothing(read_habit):
    run = read_habit
    r = run("edit", "Read", "--every", "weekly", "--target", "4", "--dry-run")
    assert r.code == 0
    assert "Would change 'Read'" in r.out and "Dry run: nothing was saved." in r.out
    h = _listed(run)
    assert (h["every"], h["target"], h["current_streak"]) == ("daily", 1, 8)


def test_edit_without_changes(read_habit):
    run = read_habit
    r = run("edit", "Read", "--target", "1")
    assert r.code == 0 and "already daily, 1 time per day; nothing changed" in r.out
    assert run("edit", "Read", "--every", "daily", "--json").json()["changed"] is False


def test_edit_needs_an_option_and_an_existing_habit(run):
    run("add", "Read")
    r = run("edit", "Read")
    assert r.code == 1 and "pass --every and/or --target" in r.err
    r = run("edit", "Nope", "--target", "2")
    assert r.code == 1 and "no habit named 'Nope'" in r.err


@pytest.mark.parametrize("argv", [["--target", "0"], ["--target", "x"], ["--every", "monthly"]])
def test_edit_bad_values_are_usage_errors(run, argv):
    run("add", "Read")
    assert run("edit", "Read", *argv).code == 2


def test_edit_archived_habit_keeps_it_archived(read_habit):
    run = read_habit
    run("archive", "Read")
    assert run("edit", "Read", "--target", "2").code == 0
    h = _listed(run)
    assert h["archived"] is True and h["target"] == 2


def test_update_habit_db_level(tmp_path):
    conn = db.connect(tmp_path / "h.db")
    try:
        habit = db.add_habit(conn, "Gym", "daily", 1, date(2026, 3, 1))
        db.add_completion(conn, habit, date(2026, 3, 2), 3)
        updated = db.update_habit(conn, habit, target=3)
        assert (updated.every, updated.target) == ("daily", 3)
        updated = db.update_habit(conn, updated, every="weekly")
        assert (updated.every, updated.target) == ("weekly", 3)
        assert db.completion_counts(conn, updated) == {date(2026, 3, 2): 3}
        with pytest.raises(db.HabitlogError):
            db.update_habit(conn, updated, target=0)
        with pytest.raises(db.HabitlogError):
            db.update_habit(conn, updated, every="monthly")
    finally:
        conn.close()

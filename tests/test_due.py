"""`habitlog due`: habits whose current period isn't met yet."""

from __future__ import annotations

import re
from datetime import date

from habitlog.cli import EXIT_DUE

# The `run` fixture uses Wednesday 2026-03-04 as today.
SATURDAY = date(2026, 3, 7)
ANSI = re.compile(r"\033\[[0-9;]*m")


def _setup(run):
    assert run("add", "Read").code == 0
    assert run("add", "Water", "--target", "8").code == 0
    assert run("add", "Gym", "--every", "weekly", "--target", "3").code == 0
    assert run("add", "Stretch", "--every", "weekdays").code == 0
    assert run("done", "Water", "--count", "3").code == 0
    # Monday of this week counts towards the weekly habit.
    assert run("done", "Gym", "--date", "2026-03-02").code == 0
    assert run("done", "Stretch").code == 0


def test_due_lists_unmet_habits_and_exits_with_due_code(run):
    _setup(run)
    r = run("due")
    assert r.code == EXIT_DUE, r.err
    lines = r.out.splitlines()
    assert lines[0] == "Due on 2026-03-04: 3 of 4 habits"
    assert lines[1].split() == ["HABIT", "EVERY", "DONE", "LEFT"]
    names = [line.split()[0] for line in lines[2:]]
    assert names == ["Gym", "Read", "Water"]  # Stretch is done today
    gym = next(line for line in lines if line.startswith("Gym"))
    assert "1/3" in gym and "2 more this week (5 days left)" in gym
    water = next(line for line in lines if line.startswith("Water"))
    assert "3/8" in water and "5 more" in water
    assert "\033[" not in r.out  # captured output is not a terminal


def test_due_json(run):
    _setup(run)
    r = run("due", "--json")
    assert r.code == EXIT_DUE
    data = r.json()
    assert data["date"] == "2026-03-04" and data["habits"] == 4
    by_name = {e["name"]: e for e in data["due"]}
    assert set(by_name) == {"Gym", "Read", "Water"}
    assert by_name["Gym"] == {
        "name": "Gym",
        "every": "weekly",
        "target": 3,
        "period": "week",
        "period_start": "2026-03-02",
        "period_count": 1,
        "remaining": 2,
        "days_left": 5,
    }
    assert by_name["Read"]["remaining"] == 1 and by_name["Read"]["days_left"] == 1


def test_due_all_done_exits_zero(run):
    assert run("add", "Read").code == 0
    assert run("add", "Gym", "--every", "weekly", "--target", "2").code == 0
    assert run("done", "Read").code == 0
    assert run("done", "Gym", "--date", "2026-03-03", "--count", "2").code == 0
    r = run("due")
    assert r.code == 0
    assert r.out.strip() == "All done for 2026-03-04."
    assert run("due", "--json").json()["due"] == []


def test_due_quiet_and_count(run):
    _setup(run)
    r = run("due", "--quiet")
    assert (r.code, r.out) == (EXIT_DUE, "")
    r = run("due", "--count")
    assert (r.code, r.out.strip()) == (EXIT_DUE, "3")
    assert run("due", "-q", "--count").code == 2  # mutually exclusive


def test_due_skips_archived_and_weekend_rest(run):
    assert run("add", "Stretch", "--every", "weekdays").code == 0
    assert run("add", "Old").code == 0
    assert run("archive", "Old").code == 0
    r = run("due", today=SATURDAY)
    assert r.code == 0 and "All done for 2026-03-07." in r.out
    r = run("due")  # Wednesday: the weekday habit is due again
    assert r.code == EXIT_DUE
    assert "Due on 2026-03-04: 1 of 1 habit" in r.out
    assert "Old" not in r.out


def test_due_last_day_of_week(run):
    assert run("add", "Gym", "--every", "weekly", "--target", "3").code == 0
    sunday = date(2026, 3, 8)
    data = run("due", "--json", today=sunday).json()
    assert data["due"][0]["days_left"] == 1
    assert "3 more this week (1 day left)" in run("due", today=sunday).out


def test_due_without_habits(run):
    r = run("due")
    assert r.code == 0 and "No habits yet" in r.out
    assert run("due", "--count").out.strip() == "0"


def test_due_colours_partial_counts(run):
    _setup(run)
    r = run("--color", "always", "due")
    assert "\033[33m3/8\033[0m" in r.out
    assert "\033[33m0/1" not in r.out  # nothing logged: plain
    assert ANSI.sub("", r.out) == run("due").out

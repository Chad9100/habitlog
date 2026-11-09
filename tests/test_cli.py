from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from datetime import date

import pytest

from conftest import TODAY
from habitlog import cli

# TODAY is Wednesday 2026-03-04.


# --------------------------------------------------------------------------- add / list


def test_add_and_list_json_shape(run):
    assert run("add", "Read").code == 0
    assert run("add", "Gym", "--every", "weekly", "--target", "3").code == 0
    data = run("list", "--json").json()
    assert [h["name"] for h in data] == ["Gym", "Read"]
    gym = data[0]
    assert set(gym) == {
        "name", "every", "target", "archived", "today",
        "current_streak", "longest_streak", "streak_unit",
    }
    assert gym["every"] == "weekly" and gym["target"] == 3 and gym["streak_unit"] == "week"
    assert gym["today"] == {"status": "open", "period_count": 0}


def test_list_empty(run):
    r = run("list")
    assert r.code == 0 and "No habits yet" in r.out
    assert run("list", "--json").json() == []


def test_list_text_table(run):
    run("add", "Read")
    run("done", "Read", "--date", "2026-03-03")
    r = run("list")
    lines = r.out.splitlines()
    assert lines[0].split() == ["HABIT", "EVERY", "TARGET", "TODAY", "STREAK", "BEST"]
    assert lines[1].split() == ["Read", "daily", "1", "-", "1d", "1d"]


def test_add_duplicate_case_insensitive_fails(run):
    run("add", "Read")
    r = run("add", "READ")
    assert r.code == 1 and "already exists" in r.err


def test_add_empty_name_fails(run):
    assert run("add", "   ").code == 1


def test_add_bad_every_is_usage_error(run):
    assert run("add", "Read", "--every", "monthly").code == 2


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_add_bad_target_is_usage_error(run, value):
    assert run("add", "Read", "--target", value).code == 2


def test_missing_command_is_usage_error(run):
    assert run().code == 2


# --------------------------------------------------------------------------- done / undo


def test_done_is_case_insensitive_and_reports_streak(run):
    run("add", "Read")
    run("done", "read", "--date", "2026-03-03")
    r = run("done", "READ")
    assert r.code == 0
    assert "Current streak: 2 days" in r.out


def test_done_rejects_future_date(run):
    run("add", "Read")
    r = run("done", "Read", "--date", "2026-03-05")
    assert r.code == 1 and "future" in r.err
    assert run("list", "--json").json()[0]["longest_streak"] == 0


@pytest.mark.parametrize("bad", ["2026-13-01", "03/04/2026", "yesterday"])
def test_done_bad_date_is_usage_error(run, bad):
    run("add", "Read")
    assert run("done", "Read", "--date", bad).code == 2


def test_done_count_zero_is_usage_error(run):
    run("add", "Read")
    assert run("done", "Read", "--count", "0").code == 2


def test_done_unknown_habit(run):
    r = run("done", "Nope")
    assert r.code == 1 and "no habit named 'Nope'" in r.err


def test_done_with_count_meets_target(run):
    run("add", "Water", "--target", "8")
    run("done", "Water", "--count", "5")
    assert run("list", "--json").json()[0]["today"] == {"status": "partial", "period_count": 5}
    run("done", "Water", "--count", "3")
    item = run("list", "--json").json()[0]
    assert item["today"]["status"] == "done" and item["current_streak"] == 1


def test_undo_removes_most_recent_completion(run):
    run("add", "Water", "--target", "3")
    run("done", "Water", "--count", "2")
    run("done", "Water", "--count", "1")
    r = run("undo", "Water")
    assert r.code == 0 and "(-1, 2 left that day)" in r.out
    assert run("list", "--json").json()[0]["today"]["period_count"] == 2


def test_undo_breaks_streak(run):
    run("add", "Read")
    for d in ("2026-03-01", "2026-03-02", "2026-03-03"):
        run("done", "Read", "--date", d)
    run("undo", "Read", "--date", "2026-03-02")
    assert run("list", "--json").json()[0]["current_streak"] == 1


def test_undo_with_nothing_to_undo(run):
    run("add", "Read")
    r = run("undo", "Read", "--date", "2026-03-01")
    assert r.code == 1 and "nothing to undo" in r.err


def test_undo_future_date_rejected(run):
    run("add", "Read")
    assert run("undo", "Read", "--date", "2027-01-01").code == 1


def test_streak_survives_until_today_ends(run):
    run("add", "Read")
    run("done", "Read", "--date", "2026-03-02")
    run("done", "Read", "--date", "2026-03-03")
    assert run("list", "--json").json()[0]["current_streak"] == 2
    # The next day, with yesterday (the 4th) missed, the streak is gone.
    assert run("list", "--json", today=date(2026, 3, 5)).json()[0]["current_streak"] == 0


def test_weekday_habit_on_weekend_is_rest(run):
    run("add", "Standup", "--every", "weekdays")
    run("done", "Standup", "--date", "2026-03-06", today=date(2026, 3, 7))
    item = run("list", "--json", today=date(2026, 3, 7)).json()[0]
    assert item["today"] == {"status": "rest", "period_count": None}
    assert item["current_streak"] == 1
    assert "rest" in run("list", today=date(2026, 3, 7)).out


# --------------------------------------------------------------------------- rename / archive / remove


def test_rename_keeps_history(run):
    run("add", "Read")
    run("done", "Read")
    assert run("rename", "read", "Read books").code == 0
    data = run("list", "--json").json()
    assert data[0]["name"] == "Read books" and data[0]["current_streak"] == 1


def test_rename_conflict(run):
    run("add", "Read")
    run("add", "Run")
    r = run("rename", "Read", "run")
    assert r.code == 1 and "already exists" in r.err


def test_archive_hides_but_keeps_history(run):
    run("add", "Read")
    run("done", "Read")
    run("archive", "Read")
    assert run("list", "--json").json() == []
    archived = run("list", "--all", "--json").json()
    assert archived[0]["archived"] is True and archived[0]["current_streak"] == 1
    assert "(archived)" in run("list", "--all").out
    assert run("stats", "Read", "--json").json()["total_completions"] == 1


def test_done_on_archived_habit_fails(run):
    run("add", "Read")
    run("archive", "Read")
    assert run("done", "Read").code == 1


def test_unarchive_restores(run):
    run("add", "Read")
    run("archive", "Read")
    assert "already archived" in run("archive", "Read").out
    run("unarchive", "read")
    assert [h["name"] for h in run("list", "--json").json()] == ["Read"]


def test_remove_requires_yes(run):
    run("add", "Read")
    r = run("remove", "Read")
    assert r.code == 1 and "--yes" in r.err
    assert len(run("list", "--json").json()) == 1


def test_remove_with_yes(run):
    run("add", "Read")
    run("done", "Read")
    r = run("remove", "Read", "--yes")
    assert r.code == 0 and "1 completion" in r.out
    assert run("list", "--all", "--json").json() == []


# --------------------------------------------------------------------------- stats


def _seed(run):
    run("add", "Read")
    for d in ("2026-02-25", "2026-02-26", "2026-02-27", "2026-03-01", "2026-03-02", "2026-03-03"):
        run("done", "Read", "--date", d)


def test_stats_json_shape(run):
    _seed(run)
    s = run("stats", "Read", "--weeks", "2", "--json").json()
    assert set(s) == {
        "name", "every", "target", "archived", "weeks", "window_start", "window_end",
        "periods_total", "periods_met", "completion_rate", "current_streak",
        "longest_streak", "streak_unit", "total_completions", "days",
    }
    # Window starts at the first completion (habit created "today" but backfilled).
    assert s["window_start"] == "2026-02-25" and s["window_end"] == "2026-03-04"
    assert (s["periods_met"], s["periods_total"]) == (6, 7)
    assert s["completion_rate"] == round(6 / 7, 4)
    assert (s["current_streak"], s["longest_streak"]) == (3, 3)
    assert s["days"]["2026-03-01"] == 1 and len(s["days"]) == 6


def test_stats_text_with_ascii_heatmap(run):
    _seed(run)
    r = run("stats", "Read", "--weeks", "2", "--ascii")
    assert r.code == 0
    assert "Current streak: 3 days" in r.out
    assert "6/7 days met (85.7%)" in r.out
    assert "Wed . #" not in r.out  # today not done
    assert "Thu # " in r.out or "Thu #" in r.out
    r.out.encode("ascii")


def test_stats_unicode_heatmap_when_supported(run, monkeypatch):
    _seed(run)
    monkeypatch.setattr(cli, "can_encode", lambda text, stream=None: True)
    assert "█" in run("stats", "Read", "--weeks", "2").out


def test_stats_falls_back_to_ascii_when_stdout_cannot_encode(run, monkeypatch):
    _seed(run)
    monkeypatch.setattr(cli, "can_encode", lambda text, stream=None: False)
    out = run("stats", "Read", "--weeks", "2").out
    assert "█" not in out and "#" in out


def test_can_encode():
    assert cli.can_encode("█", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
    assert not cli.can_encode("█", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))


def test_stats_unknown_habit(run):
    assert run("stats", "Nope").code == 1


def test_stats_weekly_habit(run):
    run("add", "Gym", "--every", "weekly", "--target", "2")
    for d in ("2026-02-16", "2026-02-18", "2026-02-23", "2026-02-27", "2026-03-02"):
        run("done", "Gym", "--date", d)
    s = run("stats", "Gym", "--json").json()
    assert s["streak_unit"] == "week"
    assert (s["current_streak"], s["periods_met"], s["periods_total"]) == (2, 2, 2)


# --------------------------------------------------------------------------- export / import


def test_export_json_shape(run):
    _seed(run)
    run("add", "Gym", "--every", "weekly", "--target", "3")
    data = run("export", "--format", "json").json()
    assert data["format"] == "habitlog-export" and data["version"] == 1
    gym, read = data["habits"]
    assert gym == {
        "name": "Gym", "every": "weekly", "target": 3, "archived": False,
        "created": "2026-03-04", "completions": [],
    }
    assert read["completions"][0] == {"date": "2026-02-25", "count": 1}


def test_export_csv(run):
    _seed(run)
    run("add", "Empty")
    rows = list(csv.reader(io.StringIO(run("export", "--format", "csv").out)))
    assert rows[0] == ["habit", "every", "target", "archived", "date", "count"]
    assert ["Empty", "daily", "1", "false", "", ""] in rows
    assert ["Read", "daily", "1", "false", "2026-03-03", "1"] in rows
    assert len(rows) == 1 + 1 + 6


def test_export_to_file_and_import_round_trip(run, tmp_path, capsys):
    _seed(run)
    run("add", "Gym", "--every", "weekly", "--target", "3")
    run("done", "Gym", "--count", "2")
    run("archive", "Gym")
    out = tmp_path / "export.json"
    assert run("export", "-o", str(out)).code == 0
    other = tmp_path / "other.db"
    code = cli.main(["--db", str(other), "import", str(out)], today=TODAY)
    assert code == 0 and "2 new habits" in capsys.readouterr().out
    cli.main(["--db", str(other), "export"], today=TODAY)
    assert json.loads(capsys.readouterr().out) == json.loads(out.read_text(encoding="utf-8"))


def test_import_is_idempotent(run, tmp_path):
    _seed(run)
    run("done", "Read", "--date", "2026-03-03", "--count", "2")
    out = tmp_path / "e.json"
    run("export", "-o", str(out))
    before = run("export").json()
    r = run("import", str(out))
    assert r.code == 0 and "0 completions added" in r.out and "1 already present" in r.out
    run("import", str(out))
    assert run("export").json() == before


def test_import_merges_missing_counts(run, tmp_path):
    run("add", "Read")
    run("done", "Read", "--date", "2026-03-01")
    payload = {
        "format": "habitlog-export",
        "version": 1,
        "habits": [
            {"name": "read", "every": "weekly", "target": 5, "completions": [
                {"date": "2026-03-01", "count": 3},
                {"date": "2026-03-02", "count": 1},
            ]},
        ],
    }
    f = tmp_path / "in.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    assert "3 completions added" in run("import", str(f)).out
    h = run("export").json()["habits"][0]
    assert h["every"] == "daily" and h["target"] == 1  # existing settings win
    assert h["completions"] == [{"date": "2026-03-01", "count": 3}, {"date": "2026-03-02", "count": 1}]


@pytest.mark.parametrize(
    "content, message",
    [
        ("not json", "not valid JSON"),
        ("[]", "'habits' list"),
        ('{"habits": [{"name": "X", "every": "hourly"}]}', "unknown frequency"),
        ('{"habits": [{"name": "X", "completions": [{"date": "2099-01-01"}]}]}', "future"),
        ('{"habits": [{"name": "X", "completions": [{"date": "2026-01-01", "count": 0}]}]}', "count"),
        ('{"habits": [{"name": "X"}, {"name": "x"}]}', "duplicate"),
    ],
)
def test_import_rejects_bad_files(run, tmp_path, content, message):
    f = tmp_path / "bad.json"
    f.write_text(content, encoding="utf-8")
    r = run("import", str(f))
    assert r.code == 1 and message in r.err
    assert run("list", "--all", "--json").json() == []


def test_import_missing_file(run, tmp_path):
    r = run("import", str(tmp_path / "missing.json"))
    assert r.code == 1 and "cannot read" in r.err


# --------------------------------------------------------------------------- db location / entry points


def test_db_option_after_subcommand(tmp_path, capsys):
    path = tmp_path / "late.db"
    assert cli.main(["add", "Read", "--db", str(path)], today=TODAY) == 0
    assert path.exists()


def test_habitlog_db_env_var(tmp_path, monkeypatch, capsys):
    path = tmp_path / "nested" / "env.db"
    monkeypatch.setenv("HABITLOG_DB", str(path))
    assert cli.main(["add", "Read"], today=TODAY) == 0
    assert path.exists()


def test_python_m_habitlog_ascii_console(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="ascii", HABITLOG_DB=str(tmp_path / "sub.db"))
    def call(*args):
        return subprocess.run(
            [sys.executable, "-m", "habitlog", *args],
            capture_output=True, env=env, timeout=60,
        )
    assert call("add", "Café run").returncode == 0
    assert call("done", "café RUN").returncode == 0
    r = call("stats", "Café run", "--weeks", "3")
    assert r.returncode == 0, r.stderr
    r.stdout.decode("ascii")  # heatmap fell back to ASCII; name replaced, no crash
    assert b"#" in r.stdout


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "0.1.0" in capsys.readouterr().out

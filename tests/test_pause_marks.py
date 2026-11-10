"""Paused days are marked in the heatmaps, `month` and the HTML report."""

from __future__ import annotations

from datetime import date

from habitlog import heatmap, report
from habitlog.streaks import Rate

# The `run` fixture uses Wednesday 2026-03-04 as today.
TODAY = date(2026, 3, 4)
PAUSED = frozenset({date(2026, 3, 2), date(2026, 3, 3)})  # Mon, Tue


def test_render_marks_paused_days_without_completions():
    lines = heatmap.render({date(2026, 3, 3): 1}, 1, TODAY, weeks=1, ascii=True, paused=PAUSED)
    assert lines[1] == "Mon ~"
    assert lines[2] == "Tue #"  # a completion still wins
    assert lines[3] == "Wed ."
    assert lines[-1].endswith("~ paused")


def test_render_compact_marks_paused_days():
    lines = heatmap.render({}, 1, TODAY, weeks=1, ascii=True, compact=True, paused=PAUSED)
    assert lines[1] == "Mon ~" and lines[2] == "Tue ~"


def test_no_paused_marker_or_legend_entry_without_pauses():
    lines = heatmap.render({}, 1, TODAY, weeks=2, ascii=True)
    assert all("~" not in line for line in lines)
    assert "paused" not in lines[-1]


def test_paused_marker_is_coloured_when_colour_is_on():
    lines = heatmap.render({}, 1, TODAY, weeks=1, ascii=True, color=True, paused=PAUSED)
    assert "\033[36m~\033[0m" in lines[1]


def test_month_grid_and_strip_mark_paused_days():
    grid = heatmap.month_grid({}, 1, date(2026, 3, 1), TODAY, ascii=True, paused=PAUSED)
    assert any(" 2~" in line and " 3~" in line for line in grid)
    assert grid[-1].endswith("~ paused")
    strip = heatmap.month_strip({}, 1, date(2026, 3, 1), TODAY, ascii=True, paused=PAUSED)
    assert strip[:4] == ".~~."
    other = heatmap.month_grid({}, 1, date(2026, 2, 1), TODAY, ascii=True, paused=PAUSED)
    assert "paused" not in other[-1]


def test_stats_and_month_commands_show_pauses(run):
    assert run("add", "Run").code == 0
    assert run("done", "Run", "--date", "2026-03-03").code == 0
    assert run("pause", "Run", "--from", "2026-03-02", "--to", "2026-03-03").code == 0
    stats = run("stats", "Run", "--weeks", "1", "--ascii").out
    assert "Mon ~" in stats and "Tue #" in stats and "~ paused" in stats
    month = run("month", "Run", "--ascii").out
    assert " 2~" in month and " 3#" in month and "~ paused" in month
    overview = run("month", "--ascii").out
    assert ".~#" in overview and "~ paused" in overview


def test_commands_without_pauses_have_no_paused_legend(run):
    assert run("add", "Run").code == 0
    assert "paused" not in run("month", "--ascii").out
    assert "paused" not in run("stats", "Run", "--ascii").out


def _habit(paused, counts=None) -> report.HabitReport:
    rate = Rate(periods_met=0, periods_total=0, start=date(2026, 3, 2), end=TODAY)
    return report.HabitReport(
        name="Run", every="daily", target=1, archived=False, counts=counts or {},
        rate=rate, current_streak=0, longest_streak=0, paused=paused,
    )


def test_html_report_marks_paused_days():
    page = report.render_html([_habit(PAUSED, {date(2026, 3, 3): 1})], TODAY, weeks=1)
    assert page.count('class="pz"') == 2  # the legend swatch and the paused Monday
    assert "Mon 2026-03-02: 0 (paused)" in page
    assert "Tue 2026-03-03: 1 (paused)" in page  # completed, so shaded, but still labelled
    assert "paused (not counted)" in page


def test_html_report_without_pauses_has_no_paused_legend():
    page = report.render_html([_habit(frozenset())], TODAY, weeks=1)
    assert 'class="pz"' not in page.split("</style>")[1]
    assert "paused (not counted)" not in page

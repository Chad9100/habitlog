"""Compact / year-long terminal heatmap (``stats --year`` and ``--compact``)."""

from __future__ import annotations

from datetime import date, timedelta

from habitlog.heatmap import render, week_month

WED = date(2026, 3, 4)  # same "today" the CLI tests use
MON_NOV_9 = date(2026, 11, 9)


def _cells(line: str) -> str:
    """The cell part of a weekday row (after the 4-character "Mon " label)."""
    return line[4:]


def test_week_month_uses_the_thursday():
    assert week_month(date(2025, 12, 29)) == (2026, 1)  # Thu 1 Jan 2026
    assert week_month(date(2026, 1, 26)) == (2026, 1)  # Thu 29 Jan, Sun 1 Feb
    assert week_month(date(2026, 2, 23)) == (2026, 2)  # Thu 26 Feb, ends 1 Mar
    assert week_month(date(2026, 3, 2)) == (2026, 3)


def test_compact_groups_weeks_by_month_with_gap_columns():
    lines = render({}, 1, WED, weeks=6, ascii=True, compact=True)
    # Weeks starting 26 Jan (Jan), 2/9/16/23 Feb (Feb), 2 Mar (Mar).
    assert _cells(lines[1]) == ". .... ."
    assert _cells(lines[3]) == ". .... ."  # Wednesday: today is the last cell
    assert _cells(lines[4]) == ". ...."  # Thursday 5 March is in the future
    assert len(lines) == 9 and "target met" in lines[-1]


def test_compact_header_labels_each_month_block():
    header = render({}, 1, WED, weeks=6, ascii=True, compact=True)[0]
    # The single January column is too narrow for its label; Feb and Mar sit
    # exactly above the first column of their block.
    assert header == "      Feb  Mar"
    row = render({}, 1, WED, weeks=6, ascii=True, compact=True)[1]
    assert header.index("Feb") == 6 == row.index(" ....") + 1
    assert header.index("Mar") == len(row) - 1


def test_year_layout_fits_80_columns_and_covers_every_month():
    counts = {MON_NOV_9 - timedelta(days=i): 1 for i in range(400)}
    lines = render(counts, 1, MON_NOV_9, weeks=53, ascii=True, compact=True)
    assert max(len(line) for line in lines) <= 80
    header = lines[0]
    for name in ("Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"):
        assert name in header
    assert header.rstrip().endswith("Nov")  # the current month, at the right edge
    # 53 week cells per full row plus one gap per month boundary.
    monday_row = _cells(lines[1])
    assert monday_row.count("#") == 53
    assert monday_row.count(" ") == len(header.split()) - 1


def test_compact_shades_the_same_days_as_the_wide_layout():
    counts = {WED - timedelta(days=i): (i % 4) for i in range(60)}
    wide = render(counts, 3, WED, weeks=9, ascii=True)
    compact = render(counts, 3, WED, weeks=9, ascii=True, compact=True)
    for w, c in zip(wide[1:8], compact[1:8]):
        assert _cells(w).replace(" ", "") == _cells(c).replace(" ", "")


def test_compact_unicode_and_single_week():
    lines = render({WED: 1}, 1, WED, weeks=1, compact=True)
    assert lines[0] == "    Mar"  # the last block is always labelled
    assert _cells(lines[3]) == "█"
    assert _cells(lines[1]) == "·"


# --------------------------------------------------------------------------- CLI


def _seed(run, today: date):
    run("add", "Read", today=today)
    for i in range(0, 380, 2):
        run("done", "Read", "--date", (today - timedelta(days=i)).isoformat(), today=today)


def test_stats_year_uses_53_weeks_and_compact_layout(run):
    _seed(run, MON_NOV_9)
    r = run("stats", "Read", "--year", "--ascii", today=MON_NOV_9)
    assert r.code == 0
    assert "Last 53 weeks:" in r.out
    rows = [line for line in r.out.splitlines() if line[:4] in ("Mon ", "Tue ")]
    assert len(rows) == 2 and all(len(line) <= 80 for line in rows)
    assert "Jan" in r.out and "Jun" in r.out
    s = run("stats", "Read", "--year", "--json", today=MON_NOV_9).json()
    assert s["weeks"] == 53
    assert s["window_end"] == "2026-11-09"


def test_stats_compact_flag_with_custom_weeks(run):
    run("add", "Read")
    run("done", "Read", "--date", "2026-03-02")
    r = run("stats", "Read", "--weeks", "6", "--compact", "--ascii")
    assert r.code == 0
    assert "      Feb  Mar" in r.out
    assert "Mon . .... #" in r.out


def test_stats_default_layout_unchanged(run):
    run("add", "Read")
    r = run("stats", "Read", "--ascii")
    assert "Last 12 weeks:" in r.out
    assert "Mon . . . . . . . . . . . ." in r.out


def test_stats_year_and_weeks_are_mutually_exclusive(run):
    run("add", "Read")
    r = run("stats", "Read", "--year", "--weeks", "4")
    assert r.code == 2
    assert "not allowed with" in r.err

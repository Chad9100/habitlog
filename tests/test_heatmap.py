from __future__ import annotations

from datetime import date

from habitlog.heatmap import ASCII_CHARS, UNICODE_CHARS, level, render

WED = date(2026, 3, 4)


def test_level_thresholds():
    assert [level(c, 4) for c in (0, 1, 2, 3, 4, 9)] == [0, 1, 2, 2, 3, 3]
    assert [level(c, 1) for c in (0, 1)] == [0, 3]


def test_shape_header_seven_rows_legend():
    lines = render({}, 1, WED, weeks=6)
    assert len(lines) == 9
    assert [line[:3] for line in lines[1:8]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert "target met" in lines[-1]


def test_one_column_per_week():
    lines = render({}, 1, WED, weeks=5)
    mon = lines[1][4:].split(" ")
    assert len(mon) == 5


def test_future_days_are_blank_and_today_is_last_cell():
    lines = render({WED: 1}, 1, WED, weeks=2, ascii=True)
    assert lines[3] == "Wed . #"  # last week's Wed empty, today's done
    assert lines[4] == "Thu ."  # this Thursday is in the future -> trailing blank stripped


def test_levels_drawn_with_unicode_chars():
    counts = {date(2026, 3, 2): 1, date(2026, 3, 3): 2, WED: 4}
    lines = render(counts, 4, WED, weeks=1)
    assert lines[1].endswith(UNICODE_CHARS[1])
    assert lines[2].endswith(UNICODE_CHARS[2])
    assert lines[3].endswith(UNICODE_CHARS[3])


def test_ascii_mode_is_pure_ascii():
    counts = {date(2026, 2, d): d % 3 for d in range(1, 28)}
    text = "\n".join(render(counts, 2, WED, weeks=12, ascii=True))
    text.encode("ascii")
    assert set(ASCII_CHARS) & set(text)


def test_month_labels_in_header():
    header = render({}, 1, WED, weeks=12)[0]
    assert "Jan" in header and "Feb" in header and "Mar" in header
    assert "Dec" in header  # first column (week of 15 Dec 2025)

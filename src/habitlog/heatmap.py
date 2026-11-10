"""Text calendar heatmap: one row per weekday, one column per ISO week."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Collection, Mapping

from .colors import PAUSED_STYLE, SHADE_STYLES, paint
from .streaks import month_end, week_start

UNICODE_CHARS = ("·", "░", "▓", "█")  # · ░ ▓ █
ASCII_CHARS = (".", "-", "+", "#")
PAUSED_CHAR = "~"  # a paused day without a completion (same in ASCII mode)

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_ROW_LABEL_WIDTH = 4  # "Mon "


def level(count: int, target: int) -> int:
    """0 = nothing, 1 = under half the target, 2 = at least half, 3 = target met."""
    if count <= 0:
        return 0
    if count >= target:
        return 3
    if 2 * count >= target:
        return 2
    return 1


def shade(lvl: int, chars: tuple, color: bool = False) -> str:
    """The character for shade level ``lvl``, ANSI-coloured when ``color`` is set."""
    return paint(chars[lvl], SHADE_STYLES[lvl]) if color else chars[lvl]


def render(
    counts: Mapping[date, int],
    target: int,
    today: date,
    weeks: int = 12,
    ascii: bool = False,
    compact: bool = False,
    color: bool = False,
    paused: Collection[date] = frozenset(),
) -> list[str]:
    """Render the last ``weeks`` weeks ending with the week containing ``today``.

    ``target`` is the per-day target used for shading. Days after ``today`` are
    left blank. Returns the lines (header, seven weekday rows, legend).

    With ``compact`` each week takes one character instead of two and a blank
    column separates the months (see :func:`render_compact`), so a whole year
    fits in about 70 columns. With ``color`` the shades (and legend) are
    wrapped in ANSI colour codes; the layout is otherwise identical. Days in
    ``paused`` without a completion show ``~`` and the legend says so.
    """
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    chars = ASCII_CHARS if ascii else UNICODE_CHARS
    first = week_start(today) - timedelta(weeks=weeks - 1)
    mondays = [first + timedelta(weeks=i) for i in range(weeks)]
    if compact:
        compact_lines = _render_compact(counts, target, today, mondays, chars, color, paused)
        return compact_lines + [legend(ascii, color, bool(paused))]

    # Month header: label a column when its Monday starts a new month, as long
    # as the label doesn't collide with the previous one.
    header = [" "] * (weeks * 2 + 3)
    last_end = -1
    prev_month: tuple[int, int] | None = None
    for i, monday in enumerate(mondays):
        key = (monday.year, monday.month)
        if key != prev_month:
            pos = i * 2
            if pos > last_end:
                name = MONTH_NAMES[monday.month - 1]
                header[pos : pos + len(name)] = list(name)
                last_end = pos + len(name)
            prev_month = key

    lines = [" " * _ROW_LABEL_WIDTH + "".join(header).rstrip()]
    for wd in range(7):
        cells = []
        for monday in mondays:
            d = monday + timedelta(days=wd)
            cells.append(_day_char(counts, target, d, today, chars, color, paused))
        lines.append(f"{DAY_NAMES[wd]} " + " ".join(cells).rstrip())
    lines.append(legend(ascii, color, bool(paused)))
    return lines


def week_month(monday: date) -> tuple[int, int]:
    """The (year, month) a week column belongs to: the month of its Thursday.

    This is the ISO 8601 rule (a week belongs to the month holding most of its
    days), so a week from Mon 28 Oct to Sun 3 Nov counts as October.
    """
    thursday = monday + timedelta(days=3)
    return thursday.year, thursday.month


def _render_compact(
    counts: Mapping[date, int],
    target: int,
    today: date,
    mondays: list[date],
    chars: tuple,
    color: bool = False,
    paused: Collection[date] = frozenset(),
) -> list[str]:
    """One character per week, with a blank separator column between months.

    Columns are grouped by :func:`week_month`. Each group is labelled with its
    month name when the label fits before the next group starts (a group of
    one week at the left edge stays unlabelled); the last group may always be
    labelled because nothing follows it.
    """
    groups: list[list[date]] = []
    keys: list[tuple[int, int]] = []
    for monday in mondays:
        key = week_month(monday)
        if keys and keys[-1] == key:
            groups[-1].append(monday)
        else:
            groups.append([monday])
            keys.append(key)

    header = ""
    pos = 0
    for i, group in enumerate(groups):
        name = MONTH_NAMES[keys[i][1] - 1]
        last = i == len(groups) - 1
        if last or len(name) <= len(group) + 1:
            header = header.ljust(pos) + name
        pos += len(group) + 1

    lines = [" " * _ROW_LABEL_WIDTH + header.rstrip()]
    for wd in range(7):
        blocks = []
        for group in groups:
            cells = []
            for monday in group:
                d = monday + timedelta(days=wd)
                cells.append(_day_char(counts, target, d, today, chars, color, paused))
            blocks.append("".join(cells))
        lines.append(f"{DAY_NAMES[wd]} " + " ".join(blocks).rstrip())
    return lines


def legend(ascii: bool = False, color: bool = False, paused: bool = False) -> str:
    c = [shade(i, ASCII_CHARS if ascii else UNICODE_CHARS, color) for i in range(4)]
    text = f"{c[0]} none  {c[1]} some  {c[2]} half+  {c[3]} target met"
    if paused:
        mark = paint(PAUSED_CHAR, PAUSED_STYLE) if color else PAUSED_CHAR
        text += f"  {mark} paused"
    return text


FULL_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # locale-independent


def month_title(month: date) -> str:
    return f"{FULL_MONTH_NAMES[month.month - 1]} {month.year}"


def _day_char(
    counts: Mapping[date, int],
    target: int,
    d: date,
    today: date,
    chars: tuple,
    color: bool = False,
    paused: Collection[date] = frozenset(),
) -> str:
    if d > today:
        return " "
    count = counts.get(d, 0)
    if count <= 0 and d in paused:
        return paint(PAUSED_CHAR, PAUSED_STYLE) if color else PAUSED_CHAR
    return shade(level(count, target), chars, color)


def month_grid(
    counts: Mapping[date, int],
    target: int,
    month: date,
    today: date,
    ascii: bool = False,
    week_target: int | None = None,
    color: bool = False,
    paused: Collection[date] = frozenset(),
) -> list[str]:
    """A ``cal``-style grid of one month (weeks start on Monday).

    Each day shows its number followed by its shade (``target`` is the per-day
    target); days after ``today`` show only the number. With ``week_target``
    (weekly habits), each row ends with that ISO week's total, e.g. ``2/3``;
    the total covers the whole Monday-Sunday week, including days in the
    neighbouring months, because that is the period the habit is judged on.
    Returns the lines: weekday header, one row per week, legend.
    """
    chars = ASCII_CHARS if ascii else UNICODE_CHARS
    first = month.replace(day=1)
    last = month_end(first)
    header = "".join(f" {name}" for name in DAY_NAMES)
    if week_target is not None:
        header += "  WEEK"
    lines = [header]
    monday = week_start(first)
    while monday <= last:
        cells = []
        for i in range(7):
            d = monday + timedelta(days=i)
            if d.month != first.month or d.year != first.year:
                cells.append("    ")
            else:
                cells.append(f"{d.day:>3}{_day_char(counts, target, d, today, chars, color, paused)}")
        row = "".join(cells)
        if week_target is not None and monday <= today:
            total = sum(counts.get(monday + timedelta(days=i), 0) for i in range(7))
            row += f"  {total}/{week_target}"
        lines.append(row.rstrip())
        monday += timedelta(weeks=1)
    lines.append(legend(ascii, color, any(first <= d <= last for d in paused)))
    return lines


def month_day_header(month: date) -> tuple[str, str]:
    """Two header lines numbering the days of ``month`` (tens digit, then units)."""
    days = range(1, month_end(month).day + 1)
    tens = "".join(str(d // 10) if d % 10 == 0 else " " for d in days)
    units = "".join(str(d % 10) for d in days)
    return tens.rstrip(), units


def month_strip(
    counts: Mapping[date, int],
    target: int,
    month: date,
    today: date,
    ascii: bool = False,
    color: bool = False,
    paused: Collection[date] = frozenset(),
) -> str:
    """One character per day of ``month`` (blank after ``today``), for a one-line overview."""
    chars = ASCII_CHARS if ascii else UNICODE_CHARS
    first = month.replace(day=1)
    days = (first + timedelta(days=i) for i in range(month_end(first).day))
    return "".join(_day_char(counts, target, d, today, chars, color, paused) for d in days)

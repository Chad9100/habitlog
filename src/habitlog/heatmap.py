"""Text calendar heatmap: one row per weekday, one column per ISO week."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping

from .streaks import week_start

UNICODE_CHARS = ("·", "░", "▓", "█")  # · ░ ▓ █
ASCII_CHARS = (".", "-", "+", "#")

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


def render(
    counts: Mapping[date, int],
    target: int,
    today: date,
    weeks: int = 12,
    ascii: bool = False,
) -> list[str]:
    """Render the last ``weeks`` weeks ending with the week containing ``today``.

    ``target`` is the per-day target used for shading. Days after ``today`` are
    left blank. Returns the lines (header, seven weekday rows, legend).
    """
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    chars = ASCII_CHARS if ascii else UNICODE_CHARS
    first = week_start(today) - timedelta(weeks=weeks - 1)
    mondays = [first + timedelta(weeks=i) for i in range(weeks)]

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
            cells.append(" " if d > today else chars[level(counts.get(d, 0), target)])
        lines.append(f"{DAY_NAMES[wd]} " + " ".join(cells).rstrip())
    lines.append(legend(ascii))
    return lines


def legend(ascii: bool = False) -> str:
    c = ASCII_CHARS if ascii else UNICODE_CHARS
    return f"{c[0]} none  {c[1]} some  {c[2]} half+  {c[3]} target met"

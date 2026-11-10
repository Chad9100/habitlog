"""Self-contained HTML report: a summary table plus a year heatmap per habit.

The output is a single HTML file with inline CSS and inline SVG: no scripts,
no external fonts or stylesheets, so it opens offline and can be mailed or
archived as is. Like ``streaks``, nothing here reads the clock or the database:
the caller passes ``today`` and the per-habit data in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from typing import Collection, Mapping, Sequence

from . import __version__
from .heatmap import DAY_NAMES, MONTH_NAMES, level
from .streaks import Rate, is_weekday, streak_unit, week_start

CELL = 11  # px, one day
STEP = 13  # px, cell plus gap
LABEL_W = 30  # px, room for "Mon" on the left
HEADER_H = 15  # px, room for month names on top

LEVEL_TEXT = ("none", "some", "half+", "target met")


@dataclass(frozen=True)
class HabitReport:
    """Everything the report shows for one habit (computed by the caller)."""

    name: str
    every: str
    target: int
    archived: bool
    counts: Mapping[date, int]
    rate: Rate
    current_streak: int
    longest_streak: int
    notes: Mapping[date, Sequence[str]] = field(default_factory=dict)
    paused: Collection[date] = frozenset()


def window_start(today: date, weeks: int) -> date:
    """Monday of the first column when the last of ``weeks`` columns holds ``today``."""
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    return week_start(today) - timedelta(weeks=weeks - 1)


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def _cell_title(
    d: date, count: int, day_target: int, notes: Sequence[str], paused: bool = False
) -> str:
    text = f"{DAY_NAMES[d.weekday()]} {d.isoformat()}: {count}"
    if day_target > 1:
        text += f"/{day_target}"
    if paused:
        text += " (paused)"
    for note in notes:
        text += f"\n- {note}"
    return text


def heatmap_svg(h: HabitReport, today: date, weeks: int) -> str:
    """One SVG grid: a column per ISO week, a row per weekday, days after ``today`` left out.

    Weekly habits are shaded against 1 per day (the target is per week); for
    ``weekdays`` habits, Saturdays and Sundays without completions are drawn as
    rest days because they never count.
    """
    first = window_start(today, weeks)
    day_target = 1 if h.every == "weekly" else h.target
    width = LABEL_W + weeks * STEP
    height = HEADER_H + 7 * STEP
    parts = [
        f'<svg class="heatmap" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(h.name)}: daily completions, {weeks} weeks">'
    ]
    for wd in (0, 2, 4):
        y = HEADER_H + wd * STEP + CELL - 1
        parts.append(f'<text class="lbl" x="0" y="{y}">{DAY_NAMES[wd]}</text>')
    last_label_x = -100
    prev_month: tuple[int, int] | None = None
    for col in range(weeks):
        monday = first + timedelta(weeks=col)
        key = (monday.year, monday.month)
        x = LABEL_W + col * STEP
        if key != prev_month:
            if x - last_label_x >= 3 * STEP:  # don't let month names overlap
                name = MONTH_NAMES[monday.month - 1]
                if monday.month == 1 or col == 0:
                    name += f" {monday.year}"
                parts.append(f'<text class="lbl" x="{x}" y="{HEADER_H - 4}">{name}</text>')
                last_label_x = x
            prev_month = key
        for wd in range(7):
            d = monday + timedelta(days=wd)
            if d > today:
                break
            count = h.counts.get(d, 0)
            is_paused = d in h.paused
            if h.every == "weekdays" and not is_weekday(d) and count == 0:
                cls = "off"
            elif is_paused and count == 0:
                cls = "pz"
            else:
                cls = f"l{level(count, day_target)}"
            title = escape(
                _cell_title(d, count, day_target, h.notes.get(d, ()), is_paused)
            )
            y = HEADER_H + wd * STEP
            parts.append(
                f'<rect class="{cls}" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2">'
                f"<title>{title}</title></rect>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _rate_cell(rate: Rate) -> str:
    if rate.rate is None:
        return "n/a"
    return f"{rate.rate * 100:.0f}%"


def _summary_table(habits: Sequence[HabitReport], first: date, today: date) -> str:
    rows = [
        "<table><thead><tr><th>Habit</th><th>Every</th><th class=num>Target</th>"
        "<th class=num>Current streak</th><th class=num>Longest streak</th>"
        "<th class=num>Periods met</th><th class=num>Rate</th>"
        "<th class=num>Completions</th><th>Last done</th></tr></thead><tbody>"
    ]
    for i, h in enumerate(habits, 1):
        unit = streak_unit(h.every)
        in_window = [d for d, c in h.counts.items() if c > 0 and first <= d <= today]
        total = sum(h.counts[d] for d in in_window)
        last = max((d for d, c in h.counts.items() if c > 0 and d <= today), default=None)
        name = escape(h.name) + (' <span class="muted">(archived)</span>' if h.archived else "")
        rows.append(
            f'<tr><td><a href="#habit-{i}">{name}</a></td><td>{h.every}</td>'
            f"<td class=num>{h.target}</td>"
            f"<td class=num>{_plural(h.current_streak, unit)}</td>"
            f"<td class=num>{_plural(h.longest_streak, unit)}</td>"
            f"<td class=num>{h.rate.periods_met}/{h.rate.periods_total}</td>"
            f"<td class=num>{_rate_cell(h.rate)}</td>"
            f"<td class=num>{total}</td>"
            f"<td>{last.isoformat() if last else '-'}</td></tr>"
        )
    rows.append("</tbody></table>")
    return "".join(rows)


_CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--card:#f6f8fa;
--l0:#ebedf0;--l1:#9be9a8;--l2:#40c463;--l3:#216e39;--off:transparent;--pz:#79c0ff}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;
--line:#30363d;--card:#161b22;--l0:#21262d;--l1:#0e4429;--l2:#006d32;--l3:#39d353;--pz:#1f4f7a}}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0 0 2px}
.muted{color:var(--muted)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;margin:16px 0 24px;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600}.num{text-align:right}
a{color:inherit}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:14px 16px;margin:0 0 16px}
section p{margin:0 0 10px}
.heatmap text.lbl{font-size:10px;fill:var(--muted)}
.l0{fill:var(--l0)}.l1{fill:var(--l1)}.l2{fill:var(--l2)}.l3{fill:var(--l3)}
.off{fill:var(--off);stroke:var(--line);stroke-width:1}
.pz{fill:var(--pz)}
.legend{display:flex;gap:12px;flex-wrap:wrap;align-items:center;font-size:12px}
.legend svg{vertical-align:-2px;margin-right:4px}
footer{font-size:12px;margin-top:24px}
"""


def _legend(rest_days: bool, paused: bool = False) -> str:
    items = []
    for i, text in enumerate(LEVEL_TEXT):
        items.append(
            f'<span><svg width="{CELL}" height="{CELL}"><rect class="l{i}" width="{CELL}" '
            f'height="{CELL}" rx="2"/></svg>{text}</span>'
        )
    if rest_days:
        items.append(
            f'<span><svg width="{CELL}" height="{CELL}"><rect class="off" x="0.5" y="0.5" '
            f'width="{CELL - 1}" height="{CELL - 1}" rx="2"/></svg>weekend '
            "(not counted for weekdays habits)</span>"
        )
    if paused:
        items.append(
            f'<span><svg width="{CELL}" height="{CELL}"><rect class="pz" width="{CELL}" '
            f'height="{CELL}" rx="2"/></svg>paused (not counted)</span>'
        )
    return '<div class="legend muted">' + "".join(items) + "</div>"


def render_html(
    habits: Sequence[HabitReport],
    today: date,
    weeks: int = 53,
    title: str = "Habit report",
) -> str:
    """The complete HTML document for ``habits`` over the ``weeks`` weeks ending today."""
    first = window_start(today, weeks)
    span = f"{first.isoformat()} to {today.isoformat()}"
    out = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title>",
        '<meta name="generator" content="habitlog ' + __version__ + '">',
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>{escape(title)}</h1>",
        f'<p class="muted">{_plural(len(habits), "habit")}, last {_plural(weeks, "week")} '
        f"({span}). Hover a day to see its count and notes.</p>",
        '<div class="scroll">',
        _summary_table(habits, first, today),
        "</div>",
    ]
    for i, h in enumerate(habits, 1):
        word = {"daily": "day", "weekdays": "weekday", "weekly": "week"}[h.every]
        archived = ", archived" if h.archived else ""
        out.append(
            f'<section id="habit-{i}"><h2>{escape(h.name)}</h2>'
            f'<p class="muted">{h.every}, {_plural(h.target, "time")} per {word}{archived}'
            f" &middot; {h.rate.periods_met}/{h.rate.periods_total} periods met "
            f"({_rate_cell(h.rate)})</p>"
            f'<div class="scroll">{heatmap_svg(h, today, weeks)}</div></section>'
        )
    out.append(
        _legend(
            any(h.every == "weekdays" for h in habits),
            any(d >= first for h in habits for d in h.paused),
        )
    )
    out.append(
        f'<footer class="muted">Generated by habitlog {__version__} on {today.isoformat()}. '
        "Streaks follow the same rules as the command line: the current period "
        "only counts once it is met.</footer>"
    )
    out.append("</main></body></html>")
    return "\n".join(out) + "\n"

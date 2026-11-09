"""Pure date and streak logic.

Nothing in this module reads the clock or touches storage: every function that
needs "now" takes ``today`` as a parameter, which keeps the rules easy to test.

Completions are passed around as ``Mapping[date, int]``: the number of times a
habit was done on each local calendar day.

Frequencies:

* ``daily``    - one period per calendar day.
* ``weekdays`` - one period per Monday-Friday day; Saturdays and Sundays are not
  periods at all, so they neither break nor extend a streak (and completions
  logged on them are ignored for streaks and rates).
* ``weekly``   - one period per ISO week (Monday-Sunday); the counts of all days
  in the week are summed and compared against the target.

A period is *met* when its total count reaches the habit's target. The period
containing ``today`` is still open: if it is not met yet, it is skipped instead
of breaking the streak, so the current streak counts up to the last full period.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator, Mapping

FREQUENCIES = ("daily", "weekdays", "weekly")

ONE_DAY = timedelta(days=1)
ONE_WEEK = timedelta(days=7)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(text: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date, raising ``ValueError`` otherwise."""
    if not isinstance(text, str) or not _DATE_RE.match(text.strip()):
        raise ValueError(f"invalid date {text!r}, expected YYYY-MM-DD")
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"invalid date {text!r}, expected YYYY-MM-DD") from None


def _check_every(every: str) -> None:
    if every not in FREQUENCIES:
        raise ValueError(f"unknown frequency {every!r}, expected one of {', '.join(FREQUENCIES)}")


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def week_start(d: date) -> date:
    """Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


def streak_unit(every: str) -> str:
    """The unit a streak is counted in: ``"week"`` for weekly habits, else ``"day"``."""
    _check_every(every)
    return "week" if every == "weekly" else "day"


def period_start(d: date, every: str) -> date:
    """The key of the period that contains ``d`` (the day itself, or its Monday)."""
    _check_every(every)
    return week_start(d) if every == "weekly" else d


def previous_period(p: date, every: str) -> date:
    """The period immediately before the period starting at ``p``."""
    _check_every(every)
    if every == "weekly":
        return week_start(p) - ONE_WEEK
    p = p - ONE_DAY
    if every == "weekdays":
        while not is_weekday(p):
            p -= ONE_DAY
    return p


def open_period(today: date, every: str) -> date | None:
    """The period containing ``today``, or ``None`` on a weekend for weekday habits."""
    _check_every(every)
    if every == "weekdays" and not is_weekday(today):
        return None
    return period_start(today, every)


def period_totals(counts: Mapping[date, int], every: str) -> dict[date, int]:
    """Sum day counts into periods (weekend days are dropped for weekday habits)."""
    _check_every(every)
    totals: dict[date, int] = defaultdict(int)
    for d, c in counts.items():
        if c <= 0:
            continue
        if every == "weekdays" and not is_weekday(d):
            continue
        totals[period_start(d, every)] += c
    return dict(totals)


def iter_periods(start: date, end: date, every: str) -> Iterator[date]:
    """Yield every period key from the period containing ``start`` up to ``end``."""
    _check_every(every)
    if every == "weekly":
        p = week_start(start)
        while p <= end:
            yield p
            p += ONE_WEEK
        return
    d = start
    while d <= end:
        if every == "daily" or is_weekday(d):
            yield d
        d += ONE_DAY


def current_streak(counts: Mapping[date, int], every: str, target: int, today: date) -> int:
    """Number of consecutive met periods ending at the current or last full period."""
    totals = period_totals(counts, every)
    p = open_period(today, every)
    if p is None:
        p = previous_period(today, every)
    elif totals.get(p, 0) < target:
        # Today's period is still open; don't let it break the streak.
        p = previous_period(p, every)
    streak = 0
    while totals.get(p, 0) >= target:
        streak += 1
        p = previous_period(p, every)
    return streak


def longest_streak(
    counts: Mapping[date, int], every: str, target: int, today: date | None = None
) -> int:
    """Longest run of consecutive met periods ever (ignoring periods after ``today``)."""
    totals = period_totals(counts, every)
    met = sorted(p for p, t in totals.items() if t >= target and (today is None or p <= today))
    best = run = 0
    prev: date | None = None
    for p in met:
        run = run + 1 if prev is not None and previous_period(p, every) == prev else 1
        best = max(best, run)
        prev = p
    return best


@dataclass(frozen=True)
class Progress:
    """How far along the open period is.

    ``status`` is ``"done"`` (target met), ``"partial"`` (some, not enough),
    ``"open"`` (nothing yet) or ``"rest"`` (weekend for a weekday habit).
    """

    period_count: int | None
    status: str


def today_progress(counts: Mapping[date, int], every: str, target: int, today: date) -> Progress:
    p = open_period(today, every)
    if p is None:
        return Progress(None, "rest")
    c = period_totals(counts, every).get(p, 0)
    if c >= target:
        return Progress(c, "done")
    return Progress(c, "partial" if c > 0 else "open")


@dataclass(frozen=True)
class Rate:
    start: date
    end: date
    periods_total: int
    periods_met: int

    @property
    def rate(self) -> float | None:
        if self.periods_total == 0:
            return None
        return self.periods_met / self.periods_total


def completion_rate(
    counts: Mapping[date, int],
    every: str,
    target: int,
    today: date,
    weeks: int,
    since: date | None = None,
) -> Rate:
    """Share of met periods over the last ``weeks`` calendar weeks.

    The window starts on the Monday ``weeks - 1`` weeks before this week (or at
    ``since``, typically when the habit was started, if that is later) and ends
    today. The open period only counts towards the total once it is met, so an
    unfinished today doesn't drag the rate down.
    """
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    start = week_start(today) - ONE_WEEK * (weeks - 1)
    if since is not None and since > start:
        start = min(since, today)
    totals = period_totals(counts, every)
    current = open_period(today, every)
    total = met = 0
    for p in iter_periods(start, today, every):
        ok = totals.get(p, 0) >= target
        if p == current and not ok:
            continue
        total += 1
        met += ok
    return Rate(start, today, total, met)

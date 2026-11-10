"""Command-line interface."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

from . import __version__, colors, db, heatmap, report, streaks
from .db import Habit, HabitlogError

EXIT_OK = 0
EXIT_ERROR = 1  # usage errors detected by argparse exit with 2
EXIT_DUE = 3  # `habitlog due`: at least one habit still needs doing
YEAR_WEEKS = 53  # stats --year: a full year plus the current week
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # locale-independent


# --------------------------------------------------------------------------- helpers


def _date_arg(text: str) -> date:
    try:
        return streaks.parse_date(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def _nonnegative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be at least 0, got {value}")
    return value


def _month_arg(text: str) -> date:
    try:
        return streaks.parse_month(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _check_not_future(day: date, today: date) -> None:
    if day > today:
        raise HabitlogError(f"{day.isoformat()} is in the future (today is {today.isoformat()})")


def _plural(n: int, unit: str, plural: str | None = None) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {plural or unit + 's'}"


def can_encode(text: str, stream: TextIO | None = None) -> bool:
    """True when ``stream`` (default: stdout) can encode ``text`` without errors."""
    stream = sys.stdout if stream is None else stream
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _safe_stdout() -> None:
    # Habit names may contain characters the console can't show; never crash on them.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _table(
    rows: list[list[str]], styles: dict[tuple[int, int], str] | None = None
) -> list[str]:
    """Align ``rows`` in columns. ``styles`` maps (row, column) to an ANSI style;
    the padding stays outside the colour codes so the columns still line up."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    styles = styles or {}
    return [
        "  ".join(
            colors.paint(c, styles.get((y, x))) + " " * (w - len(c))
            for x, (c, w) in enumerate(zip(r, widths))
        ).rstrip()
        for y, r in enumerate(rows)
    ]


def _status_style(progress: streaks.Progress) -> str:
    return colors.STATUS_STYLES.get(progress.status, "")


def _status_text(habit: Habit, progress: streaks.Progress) -> str:
    if progress.status in ("rest", "paused"):
        return progress.status
    if progress.status == "done":
        return "done"
    count = progress.period_count or 0
    if habit.every == "weekly":
        return f"{count}/{habit.target} this week"
    if habit.target > 1:
        return f"{count}/{habit.target}"
    return "-"


def _habit_summary(conn: sqlite3.Connection, habit: Habit, today: date) -> dict[str, Any]:
    counts = db.completion_counts(conn, habit)
    paused = db.paused_days(conn, habit)
    progress = streaks.today_progress(counts, habit.every, habit.target, today, paused)
    return {
        "name": habit.name,
        "every": habit.every,
        "target": habit.target,
        "archived": habit.archived,
        "today": {"status": progress.status, "period_count": progress.period_count},
        "current_streak": streaks.current_streak(
            counts, habit.every, habit.target, today, paused
        ),
        "longest_streak": streaks.longest_streak(
            counts, habit.every, habit.target, today, paused
        ),
        "streak_unit": streaks.streak_unit(habit.every),
        "_progress": progress,
    }


# --------------------------------------------------------------------------- commands


def cmd_add(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.add_habit(conn, args.name, args.every, args.target, today)
    per = {"daily": "day", "weekdays": "weekday", "weekly": "week"}[habit.every]
    print(f"Added '{habit.name}' ({_plural(habit.target, 'time')} per {per}).")
    return EXIT_OK


def cmd_rename(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    old = db.get_habit(conn, args.old).name
    habit = db.rename_habit(conn, args.old, args.new)
    print(f"Renamed '{old}' to '{habit.name}'.")
    return EXIT_OK


def _settings_text(every: str, target: int) -> str:
    per = {"daily": "day", "weekdays": "weekday", "weekly": "week"}[every]
    return f"{every}, {_plural(target, 'time')} per {per}"


def _streak_pair(
    counts: dict[date, int], every: str, target: int, today: date, paused: frozenset[date]
) -> dict[str, Any]:
    return {
        "every": every,
        "target": target,
        "current_streak": streaks.current_streak(counts, every, target, today, paused),
        "longest_streak": streaks.longest_streak(counts, every, target, today, paused),
        "streak_unit": streaks.streak_unit(every),
    }


def cmd_edit(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    """Change --every/--target. There is one setting per habit, so the whole
    history is re-evaluated with the new rule; completions are never changed."""
    if args.every is None and args.target is None:
        raise HabitlogError("nothing to change; pass --every and/or --target")
    habit = db.get_habit(conn, args.name)
    every = args.every or habit.every
    target = habit.target if args.target is None else args.target
    counts = db.completion_counts(conn, habit)
    paused = db.paused_days(conn, habit)
    before = _streak_pair(counts, habit.every, habit.target, today, paused)
    after = _streak_pair(counts, every, target, today, paused)
    changed = (every, target) != (habit.every, habit.target)
    ignored = 0
    if every == "weekdays" and habit.every != "weekdays":
        ignored = sum(c for d, c in counts.items() if not streaks.is_weekday(d))
    if changed and not args.dry_run:
        db.update_habit(conn, habit, every, target)

    if args.json:
        _print_json(
            {
                "name": habit.name,
                "changed": changed,
                "dry_run": args.dry_run,
                "before": before,
                "after": after,
                "weekend_completions_ignored": ignored,
            }
        )
        return EXIT_OK
    if not changed:
        print(f"'{habit.name}' is already {_settings_text(every, target)}; nothing changed.")
        return EXIT_OK
    verb = "Would change" if args.dry_run else "Changed"
    print(
        f"{verb} '{habit.name}' from {_settings_text(habit.every, habit.target)} "
        f"to {_settings_text(every, target)}."
    )
    rows = [["", "BEFORE", "AFTER"]]
    for label, key in (("Current streak", "current_streak"), ("Longest streak", "longest_streak")):
        rows.append(
            [
                f"  {label}",
                _plural(before[key], before["streak_unit"]),
                _plural(after[key], after["streak_unit"]),
            ]
        )
    for line in _table(rows):
        print(line)
    print("Past completions are kept as logged and re-evaluated with the new settings.")
    if ignored:
        print(f"{_plural(ignored, 'completion')} on weekends no longer count towards streaks.")
    if args.dry_run:
        print("Dry run: nothing was saved.")
    return EXIT_OK


def cmd_archive(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.get_habit(conn, args.name)
    if habit.archived:
        print(f"'{habit.name}' is already archived.")
    else:
        db.set_archived(conn, habit, True)
        print(f"Archived '{habit.name}' (history kept; 'habitlog unarchive' brings it back).")
    return EXIT_OK


def cmd_unarchive(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.get_habit(conn, args.name)
    if not habit.archived:
        print(f"'{habit.name}' is not archived.")
    else:
        db.set_archived(conn, habit, False)
        print(f"Unarchived '{habit.name}'.")
    return EXIT_OK


def cmd_remove(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.get_habit(conn, args.name)
    if not args.yes:
        raise HabitlogError(
            f"refusing to delete '{habit.name}' and all its history without --yes "
            "(use 'habitlog archive' to just hide it)"
        )
    n = db.remove_habit(conn, habit)
    print(f"Removed '{habit.name}' and {_plural(n, 'completion')}.")
    return EXIT_OK


def cmd_done(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    day = args.date or today
    _check_not_future(day, today)
    habit = db.get_habit(conn, args.name)
    if habit.archived:
        raise HabitlogError(f"'{habit.name}' is archived; unarchive it first")
    db.add_completion(conn, habit, day, args.count, args.note)
    counts = db.completion_counts(conn, habit)
    streak = streaks.current_streak(
        counts, habit.every, habit.target, today, db.paused_days(conn, habit)
    )
    unit = streaks.streak_unit(habit.every)
    print(
        f"Logged '{habit.name}' on {day.isoformat()} "
        f"({counts[day]} that day){' with a note' if args.note is not None else ''}. "
        f"Current streak: {_plural(streak, unit)}."
    )
    return EXIT_OK


def cmd_undo(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    day = args.date or today
    _check_not_future(day, today)
    habit = db.get_habit(conn, args.name)
    removed = db.undo_completion(conn, habit, day)
    left = db.completion_counts(conn, habit).get(day, 0)
    print(
        f"Removed the last completion of '{habit.name}' on {day.isoformat()} "
        f"(-{removed}, {left} left that day)."
    )
    return EXIT_OK


def _pause_text(p: db.Pause) -> str:
    if p.first == p.last:
        return f"{p.first.isoformat()} (1 day)"
    return f"{p.first.isoformat()} to {p.last.isoformat()} ({_plural(p.days, 'day')})"


def _pause_json(p: db.Pause) -> dict[str, Any]:
    return {"from": p.first.isoformat(), "to": p.last.isoformat(), "days": p.days}


def cmd_pause(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    """Pause a habit for a date range, or list its pauses with --list."""
    habit = db.get_habit(conn, args.name)
    if args.list:
        if args.start is not None:
            raise HabitlogError("--from cannot be combined with --list")
        pauses = db.list_pauses(conn, habit)
        if args.json:
            _print_json({"name": habit.name, "pauses": [_pause_json(p) for p in pauses]})
            return EXIT_OK
        if not pauses:
            print(f"'{habit.name}' has no pauses.")
            return EXIT_OK
        print(f"Pauses of '{habit.name}':")
        for p in pauses:
            state = " (now)" if p.first <= today <= p.last else ""
            print(f"  {_pause_text(p)}{state}")
        return EXIT_OK
    if args.to is None and args.days is None:
        raise HabitlogError("say how long to pause: --to DATE, --days N (or --list to show pauses)")
    if habit.archived:
        raise HabitlogError(f"'{habit.name}' is archived; unarchive it first")
    first = args.start or today
    last = args.to if args.to is not None else first + timedelta(days=args.days - 1)
    pause = db.add_pause(conn, habit, first, last)
    if args.json:
        _print_json({"name": habit.name, "pause": _pause_json(pause)})
        return EXIT_OK
    print(
        f"Paused '{habit.name}' {'on' if pause.days == 1 else 'from'} {_pause_text(pause)}. "
        "Missed days in a pause don't break the streak; completions still count."
    )
    return EXIT_OK


def cmd_unpause(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    """End the current or next pause (or remove all of them with --all)."""
    habit = db.get_habit(conn, args.name)
    if args.all:
        n = db.clear_pauses(conn, habit)
        print(f"Removed {_plural(n, 'pause')} of '{habit.name}'.")
        return EXIT_OK
    day = args.date or today
    old = db.end_pause(conn, habit, day)
    if old is None:
        raise HabitlogError(f"'{habit.name}' has no pause on or after {day.isoformat()}")
    if old.first < day:
        print(
            f"Ended the pause of '{habit.name}' that began {old.first.isoformat()}; "
            f"it now ends {(day - timedelta(days=1)).isoformat()}."
        )
    else:
        print(f"Removed the pause of '{habit.name}': {_pause_text(old)}.")
    return EXIT_OK


def cmd_list(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habits = db.list_habits(conn, include_archived=args.all)
    summaries = [_habit_summary(conn, h, today) for h in habits]
    if args.json:
        _print_json([{k: v for k, v in s.items() if not k.startswith("_")} for s in summaries])
        return EXIT_OK
    if not summaries:
        print("No habits yet. Add one with: habitlog add NAME")
        return EXIT_OK
    rows = [["HABIT", "EVERY", "TARGET", "TODAY", "STREAK", "BEST"]]
    styles: dict[tuple[int, int], str] = {}
    for h, s in zip(habits, summaries):
        if args.color_on:
            styles[(len(rows), 3)] = _status_style(s["_progress"])
        u = "w" if h.every == "weekly" else "d"
        name = h.name + (" (archived)" if h.archived else "")
        rows.append(
            [
                name,
                h.every,
                str(h.target),
                _status_text(h, s["_progress"]),
                f"{s['current_streak']}{u}",
                f"{s['longest_streak']}{u}",
            ]
        )
    for line in _table(rows, styles):
        print(line)
    return EXIT_OK


def cmd_stats(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.get_habit(conn, args.name)
    if args.year:
        args.weeks = YEAR_WEEKS
    elif args.weeks is None:
        args.weeks = 12
    counts = db.completion_counts(conn, habit)
    paused = db.paused_days(conn, habit)
    since = min([habit.created, *counts]) if counts else habit.created
    rate = streaks.completion_rate(
        counts, habit.every, habit.target, today, args.weeks, since, paused
    )
    current = streaks.current_streak(counts, habit.every, habit.target, today, paused)
    longest = streaks.longest_streak(counts, habit.every, habit.target, today, paused)
    pauses = [p for p in db.list_pauses(conn, habit) if p.last >= rate.start]
    unit = streaks.streak_unit(habit.every)
    window_start = streaks.week_start(today) - streaks.ONE_WEEK * (args.weeks - 1)
    in_window = {d: c for d, c in counts.items() if window_start <= d <= today}
    notes = db.completion_notes(conn, habit, window_start, today)

    if args.json:
        _print_json(
            {
                "name": habit.name,
                "every": habit.every,
                "target": habit.target,
                "archived": habit.archived,
                "weeks": args.weeks,
                "window_start": rate.start.isoformat(),
                "window_end": rate.end.isoformat(),
                "periods_total": rate.periods_total,
                "periods_met": rate.periods_met,
                "completion_rate": None if rate.rate is None else round(rate.rate, 4),
                "current_streak": current,
                "longest_streak": longest,
                "streak_unit": unit,
                "total_completions": sum(counts.values()),
                "days": {d.isoformat(): in_window[d] for d in sorted(in_window)},
                "notes": [{"date": d.isoformat(), "note": n} for d, n in notes],
                "pauses": [_pause_json(p) for p in pauses],
            }
        )
        return EXIT_OK

    period_word = {"daily": "days", "weekdays": "weekdays", "weekly": "weeks"}[habit.every]
    pct = "n/a" if rate.rate is None else f"{rate.rate * 100:.1f}%"
    lines = [
        f"{habit.name}  ({habit.every}, target {habit.target}"
        + (", archived)" if habit.archived else ")"),
        f"  Last {_plural(args.weeks, 'week')}: {rate.periods_met}/{rate.periods_total} "
        f"{period_word} met ({pct})",
        f"  Current streak: {_plural(current, unit)}",
        f"  Longest streak: {_plural(longest, unit)}",
        f"  Total completions: {sum(counts.values())}",
    ]
    if pauses:
        lines.append("  Paused: " + ", ".join(_pause_text(p) for p in pauses))
    lines.append("")
    for line in lines:
        print(line)
    use_ascii = args.ascii or not can_encode("".join(heatmap.UNICODE_CHARS))
    day_target = 1 if habit.every == "weekly" else habit.target
    compact = args.compact or args.year
    for line in heatmap.render(
        counts, day_target, today, args.weeks, ascii=use_ascii, compact=compact,
        color=args.color_on, paused=paused,
    ):
        print(line)
    shown = notes[-args.notes:] if args.notes else []
    if shown:
        more = len(notes) - len(shown)
        print()
        print("Recent notes" + (f" ({more} older in this window)" if more else "") + ":")
        for d, note in reversed(shown):
            print(f"  {d.isoformat()}  {note}")
    return EXIT_OK


def cmd_log(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.get_habit(conn, args.name)
    entries, total = db.completion_log(conn, habit, since=args.since, limit=args.limit or None)
    if args.json:
        _print_json(
            {
                "name": habit.name,
                "since": args.since.isoformat() if args.since else None,
                "total": total,
                "entries": [
                    {
                        "date": e.day.isoformat(),
                        "count": e.count,
                        "note": e.note,
                        "logged_at": e.logged_at,
                    }
                    for e in entries
                ],
            }
        )
        return EXIT_OK
    since_text = f" since {args.since.isoformat()}" if args.since else ""
    if not entries:
        print(f"No completions of '{habit.name}' logged{since_text}.")
        return EXIT_OK
    header = f"{habit.name}: {_plural(total, 'entry', 'entries')}{since_text}"
    if len(entries) < total:
        header += f", newest {len(entries)} shown"
    print(header)
    rows = [["DATE", "DAY", "COUNT", "NOTE"]]
    for e in entries:
        rows.append([e.day.isoformat(), _WEEKDAYS[e.day.weekday()], str(e.count), e.note or ""])
    for line in _table(rows):
        print(line)
    hidden = total - len(entries)
    if hidden:
        print(f"({_plural(hidden, 'older entry', 'older entries')} not shown; "
              "--limit 0 shows all)")
    return EXIT_OK


def _due_entry(
    habit: Habit, counts: dict[date, int], today: date, paused: frozenset[date] = frozenset()
) -> dict[str, Any] | None:
    """What is left to do for ``habit`` in today's open period, or ``None`` if nothing
    (met, a weekend for a weekday habit, or paused)."""
    period = streaks.open_period(today, habit.every)
    if period is None:  # weekend for a weekday habit
        return None
    count = streaks.period_totals(counts, habit.every).get(period, 0)
    if count >= habit.target or streaks.is_paused(period, habit.every, paused):
        return None
    weekly = habit.every == "weekly"
    return {
        "name": habit.name,
        "every": habit.every,
        "target": habit.target,
        "period": "week" if weekly else "day",
        "period_start": period.isoformat(),
        "period_count": count,
        "remaining": habit.target - count,
        # Days left in the period, today included.
        "days_left": 7 - today.weekday() if weekly else 1,
    }


def cmd_due(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    """Active habits whose current period isn't met yet; exits with EXIT_DUE if any."""
    habits = db.list_habits(conn, include_archived=False)
    due = []
    paused_now = 0  # habits left out only because today's period is paused
    for h in habits:
        counts = db.completion_counts(conn, h)
        paused = db.paused_days(conn, h)
        entry = _due_entry(h, counts, today, paused)
        if entry is not None:
            due.append(entry)
        elif paused and _due_entry(h, counts, today) is not None:
            paused_now += 1
    code = EXIT_DUE if due else EXIT_OK
    if args.quiet:
        return code
    if args.json:
        _print_json(
            {"date": today.isoformat(), "habits": len(habits), "paused": paused_now, "due": due}
        )
        return code
    if args.count:
        print(len(due))
        return code
    if not habits:
        print("No habits yet. Add one with: habitlog add NAME")
        return code
    if not due:
        if paused_now == len(habits):
            print(f"Nothing due on {today.isoformat()}: every habit is paused.")
        elif paused_now:
            print(f"All done for {today.isoformat()} ({_plural(paused_now, 'habit')} paused).")
        else:
            print(f"All done for {today.isoformat()}.")
        return code
    print(f"Due on {today.isoformat()}: {len(due)} of {_plural(len(habits), 'habit')}")
    rows = [["HABIT", "EVERY", "DONE", "LEFT"]]
    styles: dict[tuple[int, int], str] = {}
    for e in due:
        if args.color_on and e["period_count"]:
            styles[(len(rows), 2)] = colors.STATUS_STYLES["partial"]
        left = f"{e['remaining']} more"
        if e["period"] == "week":
            left += f" this week ({_plural(e['days_left'], 'day')} left)"
        rows.append([e["name"], e["every"], f"{e['period_count']}/{e['target']}", left])
    for line in _table(rows, styles):
        print(line)
    return code


def _month_rate(
    habit: Habit, counts: dict[date, int], month: date, today: date, paused: frozenset[date]
) -> streaks.Rate:
    """Periods met in ``month`` (up to today), counted from when the habit started."""
    since = min([habit.created, *counts]) if counts else habit.created
    return streaks.rate_between(
        counts, habit.every, habit.target, max(month, since), streaks.month_end(month), today,
        paused,
    )


def _rate_text(rate: streaks.Rate, every: str) -> str:
    word = {"daily": "days", "weekdays": "weekdays", "weekly": "weeks"}[every]
    pct = "n/a" if rate.rate is None else f"{rate.rate * 100:.0f}%"
    return f"{rate.periods_met}/{rate.periods_total} {word} met ({pct})"


def _month_json(
    habit: Habit, counts: dict[date, int], rate: streaks.Rate, month: date
) -> dict[str, Any]:
    last = streaks.month_end(month)
    return {
        "name": habit.name,
        "every": habit.every,
        "target": habit.target,
        "archived": habit.archived,
        "periods_total": rate.periods_total,
        "periods_met": rate.periods_met,
        "completion_rate": None if rate.rate is None else round(rate.rate, 4),
        "total_completions": sum(c for d, c in counts.items() if month <= d <= last),
        "days": {d.isoformat(): counts[d] for d in sorted(counts) if month <= d <= last},
    }


def cmd_month(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    month = args.month or today.replace(day=1)
    if month > today:
        raise HabitlogError(
            f"{month.strftime('%Y-%m')} is in the future (today is {today.isoformat()})"
        )
    if args.name:
        habits = [db.get_habit(conn, args.name)]
    else:
        habits = db.list_habits(conn, include_archived=args.all)
    data = []
    for h in habits:
        counts = db.completion_counts(conn, h)
        data.append((h, counts, _month_rate(h, counts, month, today, db.paused_days(conn, h))))

    if args.json:
        payload = {
            "month": month.strftime("%Y-%m"),
            "habits": [_month_json(h, c, r, month) for h, c, r in data],
        }
        _print_json(payload)
        return EXIT_OK

    use_ascii = args.ascii or not can_encode("".join(heatmap.UNICODE_CHARS))
    title = heatmap.month_title(month)
    if args.name:
        h, counts, rate = data[0]
        print(f"{h.name}  {title}  ({h.every}, target {h.target}"
              + (", archived)" if h.archived else ")"))
        print(f"  {_rate_text(rate, h.every)}")
        print()
        weekly = h.every == "weekly"
        grid = heatmap.month_grid(
            counts, 1 if weekly else h.target, month, today, ascii=use_ascii,
            week_target=h.target if weekly else None, color=args.color_on,
            paused=db.paused_days(conn, h),
        )
        for line in grid:
            print(line)
        return EXIT_OK

    if not data:
        print("No habits yet. Add one with: habitlog add NAME")
        return EXIT_OK
    names = [h.name + (" (archived)" if h.archived else "") for h, _, _ in data]
    width = max(len(title), *(len(n) for n in names)) + 2
    tens, units = heatmap.month_day_header(month)
    print(title.ljust(width) + tens)
    print(" " * width + units)
    first, last = month, heatmap.month_end(month)
    any_paused = False
    for name, (h, counts, rate) in zip(names, data):
        paused = db.paused_days(conn, h)
        any_paused = any_paused or any(first <= d <= last for d in paused)
        strip = heatmap.month_strip(
            counts, 1 if h.every == "weekly" else h.target, month, today, ascii=use_ascii,
            color=args.color_on, paused=paused,
        )
        print(f"{name.ljust(width)}{strip}  {_rate_text(rate, h.every)}")
    print(heatmap.legend(use_ascii, args.color_on, any_paused))
    return EXIT_OK


def cmd_report(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habits = db.list_habits(conn, include_archived=args.all)
    if not habits:
        archived = not args.all and db.list_habits(conn, include_archived=True)
        hint = " (archived habits need --all)" if archived else ""
        raise HabitlogError(f"no habits to report on{hint}")
    first = report.window_start(today, args.weeks)
    reports = []
    for h in habits:
        counts = db.completion_counts(conn, h)
        paused = db.paused_days(conn, h)
        since = min([h.created, *counts]) if counts else h.created
        notes: dict[date, list[str]] = {}
        for d, note in db.completion_notes(conn, h, first, today):
            notes.setdefault(d, []).append(note)
        reports.append(
            report.HabitReport(
                name=h.name,
                every=h.every,
                target=h.target,
                archived=h.archived,
                counts=counts,
                rate=streaks.rate_between(
                    counts, h.every, h.target, max(first, since), today, today, paused
                ),
                current_streak=streaks.current_streak(counts, h.every, h.target, today, paused),
                longest_streak=streaks.longest_streak(counts, h.every, h.target, today, paused),
                notes=notes,
                paused=paused,
            )
        )
    title = args.title or "Habit report"
    document = report.render_html(reports, today, args.weeks, title)
    if args.html == "-":
        sys.stdout.write(document)
        return EXIT_OK
    try:
        with open(args.html, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(document)
    except OSError as exc:
        raise HabitlogError(f"cannot write {args.html}: {exc.strerror or exc}") from None
    print(
        f"Wrote a report of {_plural(len(reports), 'habit')} over "
        f"{_plural(args.weeks, 'week')} to {args.html}."
    )
    return EXIT_OK


def cmd_export(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    data = db.export_data(conn)
    out: TextIO
    if args.output:
        out = open(args.output, "w", encoding="utf-8", newline="")
    else:
        out = sys.stdout
    try:
        if args.format == "json":
            out.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        else:
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(["habit", "every", "target", "archived", "date", "count", "notes"])
            for h in data["habits"]:
                base = [h["name"], h["every"], h["target"], str(h["archived"]).lower()]
                if not h["completions"]:
                    writer.writerow(base + ["", "", ""])
                for c in h["completions"]:
                    writer.writerow(base + [c["date"], c["count"], " | ".join(c.get("notes", []))])
    finally:
        if out is not sys.stdout:
            out.close()
    if args.output:
        print(f"Exported {_plural(len(data['habits']), 'habit')} to {args.output}.")
    return EXIT_OK


def cmd_import(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    try:
        if args.file == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.file).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise HabitlogError(f"cannot read {args.file}: {exc.strerror or exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HabitlogError(f"{args.file} is not valid JSON: {exc}") from None
    result = db.import_data(conn, data, today)
    print(
        f"Imported: {_plural(result.habits_created, 'new habit')}, "
        f"{result.habits_existing} already present, "
        f"{_plural(result.completions_added, 'completion')} added"
        + (f", {_plural(result.notes_added, 'note')} added" if result.notes_added else "")
        + (f", {_plural(result.pauses_added, 'pause')} added" if result.pauses_added else "")
        + (
            f", {_plural(result.notes_skipped, 'note')} skipped (no free completion that day)"
            if result.notes_skipped
            else ""
        )
        + "."
    )
    return EXIT_OK


def _count_habits(path: Path) -> int | None:
    """Active habits in a database file, opened read-only; None if unreadable."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError, ValueError):
        return None
    try:
        return conn.execute("SELECT COUNT(*) FROM habits WHERE archived = 0").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def cmd_profiles(args: argparse.Namespace, today: date) -> int:
    choice = db.choose_db(args.db, args.profile)
    rows_data = []
    for name in db.list_profiles():
        path = db.profile_db_path(name)
        exists = path.is_file()
        rows_data.append({
            "name": name,
            "path": str(path),
            "exists": exists,
            "habits": (_count_habits(path) if exists else 0),
            "active": choice.profile == name,
        })
    if args.json:
        _print_json({
            "active": choice.profile,
            "database": str(choice.path),
            "source": choice.source,
            "profiles": rows_data,
        })
        return EXIT_OK
    rows = [["", "PROFILE", "HABITS", "DATABASE"]]
    for r in rows_data:
        habits = "?" if r["habits"] is None else str(r["habits"])
        where = r["path"] if r["exists"] else f"{r['path']} (not created yet)"
        rows.append(["*" if r["active"] else "", r["name"], habits, where])
    for line in _table(rows):
        print(line.rstrip())
    if choice.profile is None:
        print(f"Using {choice.path} from {choice.source}, not a profile.")
    elif choice.source != "default":
        print(f"Active profile {choice.profile!r} chosen by {choice.source}.")
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    db_help = "database file (default: $HABITLOG_DB, else a per-user data folder)"
    profile_help = (
        "use the named profile's own database (default: $HABITLOG_PROFILE, else 'default')"
    )
    color_help = (
        "colour heatmaps and statuses: auto (default; only on a terminal and "
        "when NO_COLOR is not set), always or never"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", metavar="PATH", default=argparse.SUPPRESS, help=db_help)
    common.add_argument(
        "--profile", metavar="NAME", default=argparse.SUPPRESS, help=profile_help
    )
    common.add_argument(
        "--color", choices=colors.WHEN_CHOICES, default=argparse.SUPPRESS, metavar="WHEN",
        help=color_help,
    )

    parser = argparse.ArgumentParser(
        prog="habitlog", description="Track habits and streaks from the terminal."
    )
    parser.add_argument("--version", action="version", version=f"habitlog {__version__}")
    parser.add_argument("--db", metavar="PATH", default=None, help=db_help)
    parser.add_argument("--profile", metavar="NAME", default=None, help=profile_help)
    parser.add_argument(
        "--color", choices=colors.WHEN_CHOICES, default="auto", metavar="WHEN", help=color_help
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def add(name: str, func: Callable[..., int], help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[common], help=help, description=help)
        p.set_defaults(func=func)
        return p

    p = add("add", cmd_add, "add a habit")
    p.add_argument("name")
    p.add_argument("--every", choices=streaks.FREQUENCIES, default="daily")
    p.add_argument("--target", type=_positive_int, default=1, help="times per period (default 1)")

    p = add("rename", cmd_rename, "rename a habit")
    p.add_argument("old")
    p.add_argument("new")

    p = add("edit", cmd_edit, "change a habit's frequency or target (re-evaluates its history)")
    p.add_argument("name")
    p.add_argument("--every", choices=streaks.FREQUENCIES, default=None)
    p.add_argument("--target", type=_positive_int, default=None, help="times per period")
    p.add_argument(
        "--dry-run", action="store_true", help="show how the streaks would change, save nothing"
    )
    p.add_argument("--json", action="store_true")

    p = add("archive", cmd_archive, "hide a habit but keep its history")
    p.add_argument("name")
    p = add("unarchive", cmd_unarchive, "bring an archived habit back")
    p.add_argument("name")

    p = add("remove", cmd_remove, "delete a habit and all its history")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true", help="confirm the deletion")

    p = add("done", cmd_done, "record a completion")
    p.add_argument("name")
    p.add_argument("--date", type=_date_arg, help="YYYY-MM-DD (default: today)")
    p.add_argument("--count", type=_positive_int, default=1)
    p.add_argument("--note", help="attach a short note to this completion")

    p = add("undo", cmd_undo, "remove the most recent completion for a date")
    p.add_argument("name")
    p.add_argument("--date", type=_date_arg, help="YYYY-MM-DD (default: today)")

    p = add("pause", cmd_pause, "pause a habit for a date range without breaking its streak")
    p.add_argument("name")
    p.add_argument(
        "--from", dest="start", type=_date_arg, metavar="DATE",
        help="first paused day, YYYY-MM-DD (default: today)",
    )
    span = p.add_mutually_exclusive_group()
    span.add_argument("--to", type=_date_arg, metavar="DATE", help="last paused day (inclusive)")
    span.add_argument("--days", type=_positive_int, metavar="N", help="pause for N days")
    span.add_argument("--list", action="store_true", help="show the habit's pauses")
    p.add_argument("--json", action="store_true")

    p = add("unpause", cmd_unpause, "end a habit's current or next pause")
    p.add_argument("name")
    p.add_argument(
        "--date", type=_date_arg,
        help="first day back, YYYY-MM-DD (default: today); a pause starting then is removed",
    )
    p.add_argument("--all", action="store_true", help="remove every pause of the habit")

    p = add("list", cmd_list, "show habits with today's status and streaks")
    p.add_argument("--all", action="store_true", help="include archived habits")
    p.add_argument("--json", action="store_true")

    p = add(
        "due", cmd_due,
        f"list habits not yet met today or this week (exit code {EXIT_DUE} if any are due)",
    )
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true")
    out.add_argument(
        "--quiet", "-q", action="store_true", help="print nothing, only set the exit code"
    )
    out.add_argument("--count", action="store_true", help="print only the number of due habits")

    p = add("stats", cmd_stats, "completion rate, streaks and a calendar heatmap")
    p.add_argument("name")
    span = p.add_mutually_exclusive_group()
    span.add_argument("--weeks", type=_positive_int, help="weeks to cover (default 12)")
    span.add_argument(
        "--year", action="store_true",
        help=f"cover the last {YEAR_WEEKS} weeks in the compact layout (fits 80 columns)",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument("--ascii", action="store_true", help="plain ASCII heatmap")
    p.add_argument(
        "--compact", action="store_true",
        help="one character per week with a gap between months",
    )
    p.add_argument(
        "--notes", type=_nonnegative_int, default=5, metavar="N",
        help="show the N most recent notes in the window (default 5, 0 hides them)",
    )

    p = add("log", cmd_log, "list a habit's logged completions, newest first")
    p.add_argument("name")
    p.add_argument(
        "--limit", type=_nonnegative_int, default=20, metavar="N",
        help="show at most N entries (default 20, 0 shows all)",
    )
    p.add_argument("--since", type=_date_arg, metavar="DATE", help="only entries on or after DATE")
    p.add_argument("--json", action="store_true")

    p = add("month", cmd_month, "a month calendar for one habit, or an overview of all habits")
    p.add_argument("name", nargs="?", help="habit to show (default: one row per habit)")
    p.add_argument(
        "--month", type=_month_arg, metavar="YYYY-MM", help="month to show (default: this month)"
    )
    p.add_argument("--all", action="store_true", help="include archived habits in the overview")
    p.add_argument("--json", action="store_true")
    p.add_argument("--ascii", action="store_true", help="plain ASCII shading")

    p = add("report", cmd_report, "write a self-contained HTML report with a heatmap per habit")
    p.add_argument(
        "--html", required=True, metavar="FILE", help="HTML file to write, or - for stdout"
    )
    p.add_argument(
        "--weeks", type=_positive_int, default=53, help="weeks to cover (default 53, about a year)"
    )
    p.add_argument("--all", action="store_true", help="include archived habits")
    p.add_argument("--title", help='page title (default "Habit report")')

    p = add("profiles", cmd_profiles, "list profiles and their databases; * marks the active one")
    p.set_defaults(needs_db=False)
    p.add_argument("--json", action="store_true")

    p = add("export", cmd_export, "export all habits and completions")
    p.add_argument("--format", choices=("json", "csv"), default="json")
    p.add_argument("--output", "-o", metavar="FILE", help="write to FILE instead of stdout")

    p = add("import", cmd_import, "merge a JSON export (safe to repeat)")
    p.add_argument("file", help="JSON file from 'habitlog export', or - for stdin")
    return parser


def main(argv: Sequence[str] | None = None, *, today: date | None = None) -> int:
    """Entry point. ``today`` can be injected (tests); it defaults to the local date."""
    _safe_stdout()
    args = build_parser().parse_args(argv)
    today = today or date.today()
    args.color_on = colors.use_color(args.color)
    try:
        if not getattr(args, "needs_db", True):
            return args.func(args, today)
        path = db.resolve_db_path(args.db, profile=args.profile)
        try:
            conn = db.connect(path)
        except (sqlite3.Error, OSError) as exc:
            raise HabitlogError(f"cannot open database {path}: {exc}") from None
        try:
            return args.func(args, conn, today)
        finally:
            conn.close()
    except HabitlogError as exc:
        print(f"habitlog: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

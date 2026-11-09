"""Command-line interface."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

from . import __version__, db, heatmap, streaks
from .db import Habit, HabitlogError

EXIT_OK = 0
EXIT_ERROR = 1  # usage errors detected by argparse exit with 2


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


def _check_not_future(day: date, today: date) -> None:
    if day > today:
        raise HabitlogError(f"{day.isoformat()} is in the future (today is {today.isoformat()})")


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


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


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


def _status_text(habit: Habit, progress: streaks.Progress) -> str:
    if progress.status == "rest":
        return "rest"
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
    progress = streaks.today_progress(counts, habit.every, habit.target, today)
    return {
        "name": habit.name,
        "every": habit.every,
        "target": habit.target,
        "archived": habit.archived,
        "today": {"status": progress.status, "period_count": progress.period_count},
        "current_streak": streaks.current_streak(counts, habit.every, habit.target, today),
        "longest_streak": streaks.longest_streak(counts, habit.every, habit.target, today),
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
    streak = streaks.current_streak(counts, habit.every, habit.target, today)
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
    for h, s in zip(habits, summaries):
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
    for line in _table(rows):
        print(line)
    return EXIT_OK


def cmd_stats(args: argparse.Namespace, conn: sqlite3.Connection, today: date) -> int:
    habit = db.get_habit(conn, args.name)
    counts = db.completion_counts(conn, habit)
    since = min([habit.created, *counts]) if counts else habit.created
    rate = streaks.completion_rate(counts, habit.every, habit.target, today, args.weeks, since)
    current = streaks.current_streak(counts, habit.every, habit.target, today)
    longest = streaks.longest_streak(counts, habit.every, habit.target, today)
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
        "",
    ]
    for line in lines:
        print(line)
    use_ascii = args.ascii or not can_encode("".join(heatmap.UNICODE_CHARS))
    day_target = 1 if habit.every == "weekly" else habit.target
    for line in heatmap.render(counts, day_target, today, args.weeks, ascii=use_ascii):
        print(line)
    shown = notes[-args.notes:] if args.notes else []
    if shown:
        more = len(notes) - len(shown)
        print()
        print("Recent notes" + (f" ({more} older in this window)" if more else "") + ":")
        for d, note in reversed(shown):
            print(f"  {d.isoformat()}  {note}")
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
        + (
            f", {_plural(result.notes_skipped, 'note')} skipped (no free completion that day)"
            if result.notes_skipped
            else ""
        )
        + "."
    )
    return EXIT_OK


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    db_help = "database file (default: $HABITLOG_DB, else a per-user data folder)"
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", metavar="PATH", default=argparse.SUPPRESS, help=db_help)

    parser = argparse.ArgumentParser(
        prog="habitlog", description="Track habits and streaks from the terminal."
    )
    parser.add_argument("--version", action="version", version=f"habitlog {__version__}")
    parser.add_argument("--db", metavar="PATH", default=None, help=db_help)
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

    p = add("list", cmd_list, "show habits with today's status and streaks")
    p.add_argument("--all", action="store_true", help="include archived habits")
    p.add_argument("--json", action="store_true")

    p = add("stats", cmd_stats, "completion rate, streaks and a calendar heatmap")
    p.add_argument("name")
    p.add_argument("--weeks", type=_positive_int, default=12)
    p.add_argument("--json", action="store_true")
    p.add_argument("--ascii", action="store_true", help="plain ASCII heatmap")
    p.add_argument(
        "--notes", type=_nonnegative_int, default=5, metavar="N",
        help="show the N most recent notes in the window (default 5, 0 hides them)",
    )

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
    try:
        path = db.resolve_db_path(args.db)
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

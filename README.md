# habitlog

A personal habit and streak tracker for the terminal. You tell it what you did,
it keeps a local SQLite file, and it shows you streaks, completion rates and a
small calendar heatmap. No account, no server, no dependencies.

```
$ habitlog list
HABIT          EVERY     TARGET  TODAY          STREAK  BEST
Gym            weekly    3       0/3 this week  4w      5w
Read 20 pages  daily     1       -              9d      29d
Stretch        weekdays  1       -              10d     39d
Water          daily     8       3/8            2d      2d
```

## Who it's for

People who live in a terminal and want a habit tracker that is fast to use
(`habitlog done read`), keeps its data in one plain file they own, and can be
scripted (`--json` output, JSON import/export).

## Features

- Three kinds of habits: `daily`, `weekdays` (Mon-Fri; weekends neither break
  nor extend a streak) and `weekly` (ISO weeks, Monday to Sunday).
- Targets per period: "drink water 8 times a day", "gym 3 times a week".
- Current and longest streaks. Today (or this week) is still open, so the
  current streak doesn't drop to zero just because you haven't done it *yet*.
- Backfill with `--date`, log several at once with `--count`, `undo` mistakes.
- Archive habits to hide them without losing history.
- `stats`: completion rate over the last N weeks plus a heatmap (falls back to
  ASCII automatically when the console can't show block characters, or with
  `--ascii`).
- Export to CSV or JSON; import JSON back. Import is idempotent: importing the
  same file twice does not duplicate completions.

## Built with

Python 3.10+ and the standard library only: `sqlite3`, `argparse`, `datetime`,
`json`, `csv`. Tests use pytest. The streak rules live in a pure module
(`habitlog/streaks.py`) that takes `today` as a parameter, which keeps the date
math deterministic and heavily tested.

## Install

```
pip install git+https://github.com/Chad9100/habitlog.git
```

or from a clone:

```
git clone https://github.com/Chad9100/habitlog.git
cd habitlog
pip install .
```

This installs a `habitlog` command; `python -m habitlog` works too.

## Usage

The output below is real, captured from a demo database filled with made-up
habits. About ten weeks of history were backfilled with `done --date`:

```
habitlog add "Read 20 pages"
habitlog add Stretch --every weekdays
habitlog add Gym --every weekly --target 3
habitlog add Water --target 8
habitlog add Guitar
habitlog done Gym --date 2026-09-02
habitlog done Water --date 2026-09-02 --count 8
...
habitlog archive Guitar
```

### Logging

Habit names are case-insensitive. `--date` defaults to today (your local date)
and `--count` defaults to 1. Dates in the future are rejected.

```
$ habitlog done Stretch
Logged 'Stretch' on 2026-11-09 (1 that day). Current streak: 11 days.

$ habitlog undo Stretch
Removed the last completion of 'Stretch' on 2026-11-09 (-1, 0 left that day).

$ habitlog done "Read 20 pages" --date 2099-01-01
habitlog: error: 2099-01-01 is in the future (today is 2026-11-09)
```

### List

`list` shows active habits; `list --all` includes archived ones.

```
$ habitlog list --all
HABIT              EVERY     TARGET  TODAY          STREAK  BEST
Guitar (archived)  daily     1       -              0d      1d
Gym                weekly    3       0/3 this week  4w      5w
Read 20 pages      daily     1       -              9d      29d
Stretch            weekdays  1       -              10d     39d
Water              daily     8       3/8            2d      2d
```

`TODAY` is `done`, a partial count like `3/8`, `-` when nothing is logged yet,
or `rest` for a weekday habit on a weekend.

### Stats and heatmap

```
$ habitlog stats "Read 20 pages"
Read 20 pages  (daily, target 1)
  Last 12 weeks: 66/70 days met (94.3%)
  Current streak: 9 days
  Longest streak: 29 days
  Total completions: 66

    Aug Sep     Oct     Nov
Mon · █ █ █ █ █ █ █ █ █ █ ·
Tue · █ █ █ █ · █ █ █ █ █
Wed · █ █ █ █ · █ █ █ █ █
Thu · █ █ █ █ █ █ · █ █ █
Fri · █ █ █ █ █ █ █ █ · █
Sat · █ █ █ █ █ █ █ █ █ █
Sun · █ █ █ █ █ █ █ █ █ █
· none  ░ some  ▓ half+  █ target met
```

One row per weekday, one column per week, newest week on the right; days after
today are blank. The rate counts periods since the habit started (at most N
weeks back) and only counts today once it is met. With a target above 1, the
shading shows partial days:

```
$ habitlog stats Water --weeks 4
Water  (daily, target 8)
  Last 4 weeks: 13/21 days met (61.9%)
  Current streak: 2 days
  Longest streak: 2 days
  Total completions: 563

    Oct Nov
Mon █ █ █ ░
Tue ▓ ▓ █
Wed █ █ ▓
Thu ▓ █ █
Fri █ ▓ ▓
Sat █ █ █
Sun ▓ ▓ █
· none  ░ some  ▓ half+  █ target met
```

Weekly habits count whole ISO weeks. `--ascii` forces plain characters (used
automatically when stdout can't encode the block characters):

```
$ habitlog stats Gym --weeks 8 --ascii
Gym  (weekly, target 3)
  Last 8 weeks: 6/7 weeks met (85.7%)
  Current streak: 4 weeks
  Longest streak: 5 weeks
  Total completions: 29

    Sep Oct     Nov
Mon # # # # # # # .
Tue . . . . . . .
Wed # # . # # # #
Thu . . . . . . .
Fri # # # # # # #
Sat . . . . . . .
Sun . . . . . . .
. none  - some  + half+  # target met
```

### JSON output

`list --json` and `stats --json` are meant for scripts:

```
$ habitlog list --json
[
  {
    "name": "Gym",
    "every": "weekly",
    "target": 3,
    "archived": false,
    "today": {
      "status": "open",
      "period_count": 0
    },
    "current_streak": 4,
    "longest_streak": 5,
    "streak_unit": "week"
  },
  ...
]
```

`today.status` is one of `done`, `partial`, `open` or `rest`. `stats --json`
returns `name`, `every`, `target`, `archived`, `weeks`, `window_start`,
`window_end`, `periods_total`, `periods_met`, `completion_rate` (0-1, or null),
`current_streak`, `longest_streak`, `streak_unit`, `total_completions` and
`days` (date to count, for the days in the window).

### Managing habits

```
habitlog rename OLD NEW
habitlog archive NAME        # hidden from list, history kept
habitlog unarchive NAME
habitlog remove NAME --yes   # deletes the habit and its history
```

```
$ habitlog remove Guitar
habitlog: error: refusing to delete 'Guitar' and all its history without --yes (use 'habitlog archive' to just hide it)
```

### Export and import

```
$ habitlog export --format csv | head -3
habit,every,target,archived,date,count
Guitar,daily,1,true,2026-08-31,1
Guitar,daily,1,true,2026-09-02,1

$ habitlog export -o backup.json
Exported 5 habits to backup.json.

$ habitlog import backup.json
Imported: 0 new habits, 5 already present, 0 completions added.
```

The JSON export holds every habit (including archived ones) with its settings
and per-day completion counts. `import` matches habits by name
(case-insensitively), creates the missing ones and only adds completions up to
the imported per-day count, so running it again changes nothing. Existing
habits keep their own settings.

### Exit codes

`0` success, `1` an error such as an unknown habit, a duplicate name, a future
date or a bad import file, `2` invalid command-line usage (bad date format,
unknown option, `--count 0`).

## Data location

The database is a single SQLite file, chosen in this order:

1. `--db PATH` (before or after the command)
2. the `HABITLOG_DB` environment variable
3. the per-user default:
   - Windows: `%APPDATA%\habitlog\habitlog.db`
   - elsewhere: `$XDG_DATA_HOME/habitlog/habitlog.db`, or
     `~/.local/share/habitlog/habitlog.db` if `XDG_DATA_HOME` is unset

Parent folders are created as needed. The schema is versioned in a `meta`
table and upgraded automatically when a newer habitlog opens an older file.
Back it up with `habitlog export -o backup.json` or by copying the file.

Dates are your local calendar dates.

## Development

```
git clone https://github.com/Chad9100/habitlog.git
cd habitlog
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/pytest -q
```

Layout:

- `src/habitlog/streaks.py` pure date and streak logic (no I/O, `today` passed in)
- `src/habitlog/heatmap.py` text heatmap rendering
- `src/habitlog/db.py` SQLite storage, migrations, import/export
- `src/habitlog/cli.py` argparse commands
- `tests/` pytest suite; every test uses a temporary database

CI runs the tests on Ubuntu and Windows with Python 3.10, 3.12 and 3.13.

See [ROADMAP.md](ROADMAP.md) for what's next.

## License

MIT, see [LICENSE](LICENSE).

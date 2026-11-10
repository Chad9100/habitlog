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
- Attach a short note to a completion (`--note "chapter 4"`); recent notes show
  up in `stats` and travel with export/import.
- `log`: every logged completion of a habit, newest first, with its count and
  note (`--since`, `--limit`, `--json`).
- `month`: a calendar of one habit for a month, or a one-line-per-habit
  overview of the month with how many periods were met (`--month YYYY-MM`).
- `edit`: change a habit's frequency or target later; the whole history is
  re-evaluated with the new settings and the streak change is shown before and
  after (`--dry-run` previews it without saving).
- `report --html FILE`: a self-contained HTML page with a summary table and a
  year heatmap per habit (no scripts or external files; works offline).
- `due`: what is still left to do today or this week, with an exit code for
  shell prompts, cron jobs and scripts (`--quiet`, `--count`, `--json`).
- Profiles: keep separate sets of habits (work, home, ...) in separate
  database files with `--profile NAME` or `HABITLOG_PROFILE`; `profiles` lists them.
- Archive habits to hide them without losing history.
- `stats`: completion rate over the last N weeks plus a heatmap (falls back to
  ASCII automatically when the console can't show block characters, or with
  `--ascii`). `stats --year` shows the last 53 weeks in a compact layout with a
  gap between months that fits in 80 columns.
- Optional colour: heatmaps are shaded in greens and `list` highlights today's
  status. Only on a terminal, never when `NO_COLOR` is set (`--color` overrides).
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

### Notes

`done --note TEXT` attaches a short, single-line note (up to 500 characters;
newlines and runs of spaces collapse to one space) to that completion. `undo`
removes the most recent completion together with its note. `stats` lists the
most recent notes in its window, newest first; `--notes N` changes how many
(default 5, `--notes 0` hides them).

Real output from a separate throwaway database (one habit, about two weeks of
backfilled reading):

```
$ habitlog done "Read 20 pages" --date 2026-11-08 --note "Dune, ch. 4 - finally met Stilgar"
Logged 'Read 20 pages' on 2026-11-08 (1 that day) with a note. Current streak: 13 days.

$ habitlog done "Read 20 pages" --note "   "
habitlog: error: note must not be empty

$ habitlog stats "Read 20 pages" --weeks 3 --ascii
Read 20 pages  (daily, target 1)
  Last 3 weeks: 13/13 days met (100.0%)
  Current streak: 13 days
  Longest streak: 13 days
  Total completions: 14

    Oct
Mon . # .
Tue # #
Wed # #
Thu # #
Fri # #
Sat # #
Sun # #
. none  - some  + half+  # target met

Recent notes:
  2026-11-08  Dune, ch. 4 - finally met Stilgar
  2026-11-06  Dune, ch. 3, on the train
  2026-11-03  Dune, ch. 1-2

$ habitlog stats "Read 20 pages" --weeks 3 --notes 1
...
Recent notes (2 older in this window):
  2026-11-08  Dune, ch. 4 - finally met Stilgar
```

`stats --json` returns every note in the window, oldest first:

```
  "notes": [
    {
      "date": "2026-11-03",
      "note": "Dune, ch. 1-2"
    },
    {
      "date": "2026-11-06",
      "note": "Dune, ch. 3, on the train"
    },
    {
      "date": "2026-11-08",
      "note": "Dune, ch. 4 - finally met Stilgar"
    }
  ]
```

### Log

`habitlog log NAME` lists what you actually logged for one habit: one row per
`done`, newest first, with the day, its count and its note. It shows the 20
newest entries by default; `--limit N` changes that (`--limit 0` shows all) and
`--since YYYY-MM-DD` keeps only entries on or after that date. Archived habits
can be logged too, so their history stays readable.

Real output from a throwaway database (backfilled reading over two weeks, plus
one day of water):

```
$ habitlog log "Read 20 pages" --limit 6
Read 20 pages: 12 entries, newest 6 shown
DATE        DAY  COUNT  NOTE
2026-11-08  Sun  1      Dune, ch. 4 - finally met Stilgar
2026-11-06  Fri  1
2026-11-06  Fri  1      Dune, ch. 3, on the train
2026-11-05  Thu  1
2026-11-04  Wed  1
2026-11-03  Tue  1      Dune, ch. 1-2
(6 older entries not shown; --limit 0 shows all)

$ habitlog log "Read 20 pages" --since 2026-11-05
Read 20 pages: 4 entries since 2026-11-05
DATE        DAY  COUNT  NOTE
2026-11-08  Sun  1      Dune, ch. 4 - finally met Stilgar
2026-11-06  Fri  1
2026-11-06  Fri  1      Dune, ch. 3, on the train
2026-11-05  Thu  1

$ habitlog log Water --since 2026-11-09
No completions of 'Water' logged since 2026-11-09.
```

`log --json` returns `name`, `since` (or null), `total` (matching entries,
ignoring `--limit`) and `entries`, newest first. `logged_at` is the local time
on the computer when the entry was recorded, which differs from `date` for
backfilled entries:

```
$ habitlog log Water --since 2026-11-08 --json
{
  "name": "Water",
  "since": "2026-11-08",
  "total": 3,
  "entries": [
    {
      "date": "2026-11-08",
      "count": 1,
      "note": "after the run",
      "logged_at": "2026-11-09T17:22:53"
    },
    {
      "date": "2026-11-08",
      "count": 4,
      "note": null,
      "logged_at": "2026-11-09T17:22:53"
    },
    {
      "date": "2026-11-08",
      "count": 3,
      "note": "before work",
      "logged_at": "2026-11-09T17:22:52"
    }
  ]
}
```

### Month

`habitlog month` shows the current month for all active habits, one row per
habit and one character per day, followed by how many periods (days, weekdays
or weeks) were met so far. `habitlog month NAME` shows a `cal`-style calendar
of one habit instead. `--month YYYY-MM` picks another month (future months are
rejected), `--all` adds archived habits to the overview and `--ascii` forces
plain characters.

Real output from a throwaway database with about five weeks of made-up,
backfilled history (today was 2026-11-09, with 3 of 8 glasses of water logged):

```
$ habitlog month
November 2026           1         2         3
               123456789012345678901234567890
Gym            ·█·█·█···                       2/2 weeks met (100%)
Read 20 pages  ████████·                       8/8 days met (100%)
Stretch        ·█████···                       5/5 weekdays met (100%)
Water          ░███▓▓██░                       5/8 days met (62%)
· none  ░ some  ▓ half+  █ target met

$ habitlog month "Read 20 pages"
Read 20 pages  November 2026  (daily, target 1)
  8/8 days met (100%)

 Mon Tue Wed Thu Fri Sat Sun
                          1█
  2█  3█  4█  5█  6█  7█  8█
  9· 10  11  12  13  14  15
 16  17  18  19  20  21  22
 23  24  25  26  27  28  29
 30
· none  ░ some  ▓ half+  █ target met
```

The rate uses the same rules as `stats`: it starts when the habit started,
stops at today, and only counts today once it is met. Weekly habits are judged
on whole ISO weeks, so every week that overlaps the month counts, and the
calendar ends each row with that week's total (including days in the
neighbouring months):

```
$ habitlog month Gym --month 2026-10 --ascii
Gym  October 2026  (weekly, target 3)
  3/5 weeks met (60%)

 Mon Tue Wed Thu Fri Sat Sun  WEEK
              1.  2#  3.  4.  1/3
  5#  6.  7#  8.  9# 10. 11.  3/3
 12# 13. 14. 15. 16. 17. 18.  1/3
 19# 20. 21# 22. 23# 24. 25.  3/3
 26# 27. 28# 29. 30# 31.      3/3
. none  - some  + half+  # target met

$ habitlog month Water --month 2026-12
habitlog: error: 2026-12 is in the future (today is 2026-11-09)
```

`month --json` returns `month` and a `habits` list; each entry has `name`,
`every`, `target`, `archived`, `periods_total`, `periods_met`,
`completion_rate` (0-1, or null), `total_completions` and `days` (date to
count, for the days of that month):

```
$ habitlog month Stretch --month 2026-10 --json
{
  "month": "2026-10",
  "habits": [
    {
      "name": "Stretch",
      "every": "weekdays",
      "target": 1,
      "archived": false,
      "periods_total": 22,
      "periods_met": 21,
      "completion_rate": 0.9545,
      "total_completions": 21,
      "days": {
        "2026-10-01": 1,
        "2026-10-02": 1,
        "2026-10-05": 1,
        ...
      }
    }
  ]
}
```

### HTML report

`habitlog report --html FILE` writes a single, self-contained HTML file: a
summary table of every active habit (streaks, periods met and completion rate
over the window, completions, last day done) and a year-long heatmap per habit.
It uses inline CSS and SVG only, with no scripts or external files, so it
opens offline, follows the system's light/dark setting and can be mailed or
archived as is. Hovering a day shows its count (against the daily target) and
any notes. `--weeks N` changes the window (default 53, about a year), `--all`
adds archived habits, `--title` sets the page title and `--html -` writes the
page to stdout.

Real output from a throwaway database with about 200 days of made-up history
(today was 2026-11-09):

```
$ habitlog report --html report.html
Wrote a report of 4 habits over 53 weeks to report.html.

$ habitlog report --html q3.html --weeks 13 --title "Q3 habits"
Wrote a report of 4 habits over 13 weeks to q3.html.

$ habitlog archive Water
Archived 'Water' (history kept; 'habitlog unarchive' brings it back).

$ habitlog report --html report.html
Wrote a report of 3 habits over 53 weeks to report.html.

$ habitlog report --html report.html --all
Wrote a report of 4 habits over 53 weeks to report.html.

$ habitlog --db empty.db report --html x.html
habitlog: error: no habits to report on
```

The summary table of that last `report.html` (155 KB, 4 heatmaps), with its
cells pulled out of the HTML and joined by `|`:

```
Habit | Every | Target | Current streak | Longest streak | Periods met | Rate | Completions | Last done
Gym | weekly | 3 | 2 weeks | 4 weeks | 11/29 | 38% | 63 | 2026-11-06
Read 20 pages | daily | 1 | 3 days | 23 days | 167/199 | 84% | 167 | 2026-11-08
Stretch | weekdays | 1 | 23 days | 23 days | 108/141 | 77% | 108 | 2026-11-06
Water (archived) | daily | 8 | 0 days | 3 days | 8/59 | 14% | 326 | 2026-11-09
```

Rates follow the same rules as `stats` and `month`: they start when the habit
started (its first completion or the day it was added, whichever is earlier),
and the current day or week only counts once it is met. In the heatmaps,
weekly habits shade each day as done or not (their target applies to the whole
week), and for `weekdays` habits, Saturdays and Sundays without completions are
drawn as outlined rest days.

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

### Due

`due` lists the active habits whose current period isn't met yet: today for
`daily` and `weekdays` habits, the ISO week for `weekly` ones. Weekday habits
are never due on a weekend, and archived habits are left out.

```
$ habitlog due
Due on 2026-03-04: 3 of 4 habits
HABIT  EVERY   DONE  LEFT
Gym    weekly  1/3   2 more this week (5 days left)
Read   daily   0/1   1 more
Water  daily   3/8   5 more
$ habitlog due --count
3
```

It exits with `0` when everything is done and `3` when at least one habit is
due (`1` and `2` keep their usual meaning, see [Exit codes](#exit-codes)), so
it can drive a prompt or a reminder:

```sh
# bash prompt: show how many habits are left
PS1='$(n=$(habitlog due --count); [ "$n" != 0 ] && echo "[$n due] ")'"$PS1"
# cron, 8 pm: remind only if something is still due
0 20 * * * habitlog due --quiet; [ $? -eq 3 ] && notify-send "habitlog" "$(habitlog due)"
```

`--quiet` (`-q`) prints nothing, `--count` prints only the number, and `--json`
gives each due habit's `period` (`day` or `week`), `period_start`,
`period_count`, `target`, `remaining` and `days_left` (today included).

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

### A year at a glance

`--year` covers the last 53 weeks and switches to the compact layout: one
character per week and a blank column between months, so a whole year fits in
about 70 columns. A week belongs to the month that holds its Thursday (the ISO
8601 rule), so the week of Mon 26 Oct - Sun 1 Nov counts as October. This
demo database has about eleven months of made-up history with a summer slump:

```
$ habitlog stats "Read 20 pages" --year --notes 0
Read 20 pages  (daily, target 1)
  Last 53 weeks: 278/329 days met (84.5%)
  Current streak: 12 days
  Longest streak: 28 days
  Total completions: 278

    Nov Dec  Jan   Feb  Mar  Apr   May  Jun  Jul   Aug  Sep  Oct   Nov
Mon ··· ··██ █████ ████ ████ █████ ████ ··██ ·██·█ ██·█ ·███ █████ █·
Tue ··· ··██ █████ ████ ██·· █·███ ██·█ ████ ···██ ██·█ ███· ████· █
Wed ··· ··██ ███·█ ████ ████ █·███ ████ ███· █··█· ·███ ████ █████ █
Thu ··· ··██ ·████ ████ ████ ████· ████ ████ ··█·· ██·· ████ █████ █
Fri ··· ··██ █████ █·██ ████ █████ ████ ·█·█ █·██· ██·█ ████ █████ █
Sat ··· ··██ █████ ·███ █·██ █████ ███· ████ █··██ ██·█ ████ █████ █
Sun ··· ··██ █████ ████ ████ ·████ ████ █·██ █···█ ██·█ ████ ·██·█ █
· none  ░ some  ▓ half+  █ target met
```

`--compact` gives the same layout for any `--weeks` (`--year` and `--weeks`
can't be combined):

```
$ habitlog stats Gym --weeks 20 --compact --ascii
Gym  (weekly, target 3)
  Last 20 weeks: 10/19 weeks met (52.6%)
  Current streak: 1 week
  Longest streak: 4 weeks
  Total completions: 108

    Jul   Aug  Sep  Oct   Nov
Mon ###.# #### #### ##### #.
Tue ..... .... .... ..... .
Wed .#### ##.# ###. ##### #
Thu ..... .... .... ..... .
Fri #.#.. #### .#.# ####. #
Sat ..... .... .... ..... .
Sun ..... .... .... ..... .
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
`current_streak`, `longest_streak`, `streak_unit`, `total_completions`,
`days` (date to count, for the days in the window) and `notes` (a list of
`{"date", "note"}` for the window, oldest first).

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

### Editing a habit

```
habitlog edit NAME [--every daily|weekdays|weekly] [--target N] [--dry-run] [--json]
```

A habit has one frequency and one target, so the rule is simple: after an
edit, **all** past completions are re-evaluated with the new settings, as if
the habit had always been set up that way. Completions themselves are never
changed or deleted, so an edit is fully reversible: editing back restores the
old streaks exactly. `edit` prints the current and longest streak before and
after, and `--dry-run` shows that without saving anything. Switching to
`weekdays` reports how many weekend completions stop counting (they stay in
the database and in exports).

Captured on Monday 2026-11-09 from a separate made-up database: a daily
`Stretch` habit logged every day since 26 October except the 28th.

```
$ habitlog list
HABIT    EVERY  TARGET  TODAY  STREAK  BEST
Stretch  daily  1       done   12d     12d
$ habitlog edit Stretch --every weekdays --dry-run
Would change 'Stretch' from daily, 1 time per day to weekdays, 1 time per weekday.
                  BEFORE   AFTER
  Current streak  12 days  8 days
  Longest streak  12 days  8 days
Past completions are kept as logged and re-evaluated with the new settings.
4 completions on weekends no longer count towards streaks.
Dry run: nothing was saved.
$ habitlog edit Stretch --every weekly --target 4
Changed 'Stretch' from daily, 1 time per day to weekly, 4 times per week.
                  BEFORE   AFTER
  Current streak  12 days  2 weeks
  Longest streak  12 days  2 weeks
Past completions are kept as logged and re-evaluated with the new settings.
$ habitlog list
HABIT    EVERY   TARGET  TODAY          STREAK  BEST
Stretch  weekly  4       1/4 this week  2w      2w
$ habitlog edit Stretch --target 4
'Stretch' is already weekly, 4 times per week; nothing changed.
$ habitlog edit Stretch
habitlog: error: nothing to change; pass --every and/or --target
```

`edit --json` returns `name`, `changed`, `dry_run`, `before` and `after`
(each with `every`, `target`, `current_streak`, `longest_streak`,
`streak_unit`) and `weekend_completions_ignored`.

### Export and import

```
$ habitlog export -o backup.json
Exported 5 habits to backup.json.

$ habitlog import backup.json
Imported: 0 new habits, 5 already present, 0 completions added.
```

The CSV export has one row per habit and day, with the day's notes joined by
` | ` in the last column (from the notes demo database above):

```
$ habitlog export --format csv
habit,every,target,archived,date,count,notes
...
Read 20 pages,daily,1,false,2026-11-02,1,
Read 20 pages,daily,1,false,2026-11-03,1,"Dune, ch. 1-2"
Read 20 pages,daily,1,false,2026-11-04,1,
Read 20 pages,daily,1,false,2026-11-05,1,
Read 20 pages,daily,1,false,2026-11-06,2,"Dune, ch. 3, on the train"
...
```

The JSON export holds every habit (including archived ones) with its settings
and per-day completion counts; a day with notes also has a `notes` list
(`{"date": "2026-11-03", "count": 1, "notes": ["Dune, ch. 1-2"]}`). `import`
matches habits by name (case-insensitively), creates the missing ones and only
adds completions up to the imported per-day count, so running it again changes
nothing. Existing habits keep their own settings.

Notes merge the same way. An imported note that the day doesn't have yet is
put on one of that day's completions without a note; if every completion that
day already has a different note, it is skipped and reported, never duplicated:

```
$ habitlog --db fresh.db import backup.json
Imported: 1 new habit, 0 already present, 14 completions added, 3 notes added.
$ habitlog --db fresh.db import backup.json
Imported: 0 new habits, 1 already present, 0 completions added.
```

### Profiles

A profile is a separate database with its own habits. Pick one with
`--profile NAME` (before or after the command) or the `HABITLOG_PROFILE`
environment variable; a profile's file is created the first time you use it.

```
$ habitlog --profile work add Standup
$ habitlog --profile work add Inbox
$ habitlog add Walk                      # the default profile
$ export HABITLOG_PROFILE=work           # PowerShell: $env:HABITLOG_PROFILE = "work"
$ habitlog profiles
   PROFILE  HABITS  DATABASE
   default  1       /home/me/.local/share/habitlog/habitlog.db
*  work     2       /home/me/.local/share/habitlog/profiles/work.db
Active profile 'work' chosen by HABITLOG_PROFILE.
```

Names are 1-40 letters, digits, `-` or `_` and are case-insensitive (`Work`
and `work` are the same profile). `default` is the ordinary default database.
`habitlog profiles --json` gives the active profile, the database in use, what
chose it, and each profile's path, whether its file exists and its number of
active habits. Listing profiles never creates a database. `--db` and
`--profile` can't be combined.

### Colour

`stats`, `month` and `list` can use ANSI colour: heatmap shades go from grey
(none) through dim and normal green to bold green (target met), and the `TODAY`
column of `list` shows `done` in green, a partial count in yellow and `rest` in
grey. The characters and layout are exactly the same as without colour.

`--color WHEN` (before or after the command) chooses when:

- `auto` (default): only when output goes to a terminal, the
  [`NO_COLOR`](https://no-color.org) environment variable is unset or empty and
  `TERM` is not `dumb`. Piped or redirected output is never coloured. On
  Windows, ANSI support is switched on for the console if it is available.
- `always`: colour even when piped, e.g. `habitlog stats Gym --color always | less -R`.
- `never`: plain text.

`--json` output, exports and the HTML report are never affected.

### Exit codes

`0` success, `1` an error such as an unknown habit, a duplicate name, a future
date or a bad import file, `2` invalid command-line usage (bad date format,
unknown option, `--count 0`). `habitlog due` also exits with `3` when at
least one habit is still due.

## Data location

The database is a single SQLite file, chosen in this order:

1. `--db PATH` (before or after the command)
2. `--profile NAME`
3. the `HABITLOG_DB` environment variable
4. the `HABITLOG_PROFILE` environment variable
5. the per-user default (the `default` profile):
   - Windows: `%APPDATA%\habitlog\habitlog.db`
   - elsewhere: `$XDG_DATA_HOME/habitlog/habitlog.db`, or
     `~/.local/share/habitlog/habitlog.db` if `XDG_DATA_HOME` is unset

Other profiles live in a `profiles` folder next to the default file, e.g.
`~/.local/share/habitlog/profiles/work.db`.

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
- `src/habitlog/heatmap.py` text heatmap and month calendar rendering
- `src/habitlog/colors.py` ANSI colour and the `--color`/`NO_COLOR` decision
- `src/habitlog/report.py` self-contained HTML report (pure, `today` passed in)
- `src/habitlog/db.py` SQLite storage, migrations, import/export
- `src/habitlog/cli.py` argparse commands
- `tests/` pytest suite; every test uses a temporary database

CI runs the tests on Ubuntu and Windows with Python 3.10, 3.12 and 3.13.

See [ROADMAP.md](ROADMAP.md) for what's next.

## License

MIT, see [LICENSE](LICENSE).

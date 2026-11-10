# Roadmap

Estimates are rough working hours for one person, including tests and docs.

## v0.1 (done)

- [x] SQLite storage with a versioned schema (`meta` table + migrations)
- [x] `add`, `rename`, `archive`, `unarchive`, `remove --yes`
- [x] `done` / `undo` with `--date` and `--count`; future dates rejected
- [x] Daily, weekdays and weekly habits with targets per period
- [x] Current and longest streaks that don't break while today is still open
- [x] `list` and `stats` with `--json`; text heatmap with ASCII fallback
- [x] CSV/JSON export, idempotent JSON import
- [x] Pure, deterministic streak module and a pytest suite; CI on Ubuntu and Windows

## v0.2 - Notes and better views (about 8 h)

- [x] Notes per completion: `habitlog done read --note "chapter 4"`, shown in
      `stats` and included in export/import (schema migration 2) - 3 h
- [x] `habitlog log NAME` to list recent completions with dates, counts and notes - 1.5 h
- [x] Monthly calendar view: `habitlog month [NAME] [--month 2026-11]` - 2.5 h
- [x] `habitlog edit NAME --target/--every` with clear rules for how past streaks
      are recalculated - 1 h

## v0.3 - Reports (about 6 h)

- [x] `habitlog report --html report.html`: a single self-contained HTML file
      with a year heatmap per habit and summary table - 4 h
- [x] Year-long heatmap in the terminal: `stats --year` (53 weeks) and
      `--compact`, one column per week with month separators, fits 80 columns - 1 h
- [x] Optional colour output: `--color auto|always|never`, respecting `NO_COLOR`,
      `TERM=dumb` and non-TTY output - 1 h

## v0.4 - Reminders and profiles (about 8.75 h)

- [x] `habitlog due`: list habits not yet met for today/this week, with an exit
      code suitable for shell prompts and cron - 1.5 h
- [ ] Reminder recipes: documented cron / Task Scheduler snippets that call
      `habitlog due` and show a desktop notification - 2 h
- [x] Multiple profiles (`--profile work`, `HABITLOG_PROFILE`) mapped to
      separate database files, plus `habitlog profiles` - 2 h
- [x] Pause a habit for a date range (vacation) without breaking its streak:
      `pause`/`unpause` (schema migration 3); paused periods are skipped by
      streaks, rates and `due` - 1.5 h
- [x] Carry pauses through JSON export/import (merged, idempotent, old exports
      still import) and make `due` say when habits are paused rather than
      done (split out of the item above) - 0.75 h
- [x] Mark paused days in the terminal heatmaps, `month` and the HTML report
      (split out of the item above) - 1 h

## v0.5 - Sync via a plain file (about 5 h)

- [x] `habitlog sync FILE`: two-way merge with a JSON file kept in a synced
      folder (Dropbox, Syncthing, a git repo); builds on the idempotent import
      (additive only; deletions are the next item) - 1.5 h
- [x] `sync --dry-run` preview, and report (keep local, list differences) when
      every/target/archived differ between copies (split from the item below) - 1 h
- [x] Choose a winner for setting conflicts (`--prefer file|local`) instead of
      always keeping the local value - 0.5 h
- [ ] Track deletions/undos in the sync file so they propagate instead of being
      re-imported - 2 h

## v1.0 - Release (about 4 h)

- [ ] Publish to PyPI with a trusted-publishing GitHub Actions workflow - 1.5 h
- [x] Shell completion for bash, zsh and PowerShell: `habitlog completion SHELL`,
      generated from the parser (commands, options, fixed choices) - 1.5 h
- [ ] Complete habit names dynamically (`habitlog done <TAB>`) - 1 h
- [ ] Freeze the JSON output and export formats; document them as stable - 1 h

Total planned: about 32.75 hours.

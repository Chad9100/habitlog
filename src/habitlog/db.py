"""SQLite storage, schema migrations and JSON import/export."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .streaks import FREQUENCIES, parse_date

SCHEMA_VERSION = 3
EXPORT_FORMAT = "habitlog-export"
EXPORT_VERSION = 1
MAX_NAME_LENGTH = 100
MAX_NOTE_LENGTH = 500
MAX_PAUSE_DAYS = 366


class HabitlogError(Exception):
    """A user-facing error; the CLI prints it and exits with status 1."""


class HabitNotFound(HabitlogError):
    pass


# --------------------------------------------------------------------------- paths


def default_db_path(env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Per-user default location of the database file."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        base = env.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "habitlog" / "habitlog.db"


DEFAULT_PROFILE = "default"
_PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")


def check_profile_name(name: str) -> str:
    """Return a profile name if it is safe to use as a file name, else raise."""
    if not _PROFILE_RE.fullmatch(name):
        raise HabitlogError(
            f"invalid profile name {name!r}: use 1-40 letters, digits, '-' or '_', "
            "starting with a letter or digit"
        )
    return name


def profiles_dir(env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Folder holding one database file per named profile."""
    return default_db_path(env, platform).parent / "profiles"


def profile_db_path(
    name: str, env: Mapping[str, str] | None = None, platform: str | None = None
) -> Path:
    """Database file of a profile; ``default`` is the ordinary default database."""
    check_profile_name(name)
    if name.lower() == DEFAULT_PROFILE:
        return default_db_path(env, platform)
    return profiles_dir(env, platform) / f"{name.lower()}.db"


def list_profiles(env: Mapping[str, str] | None = None, platform: str | None = None) -> list[str]:
    """``default`` plus every profile that has a database file, sorted."""
    folder = profiles_dir(env, platform)
    names = set()
    if folder.is_dir():
        for p in folder.glob("*.db"):
            if p.is_file() and _PROFILE_RE.fullmatch(p.stem):
                names.add(p.stem.lower())
    names.discard(DEFAULT_PROFILE)
    return [DEFAULT_PROFILE, *sorted(names)]


@dataclass(frozen=True)
class DbChoice:
    """Which database to open and why (``profile`` is None for an explicit file)."""

    path: Path
    profile: str | None
    source: str  # "--db", "HABITLOG_DB", "--profile", "HABITLOG_PROFILE" or "default"


def choose_db(
    cli_db: str | None,
    cli_profile: str | None = None,
    env: Mapping[str, str] | None = None,
) -> DbChoice:
    """Command-line options beat environment variables; an explicit file beats a
    profile at the same level: ``--db``, ``--profile``, ``HABITLOG_DB``,
    ``HABITLOG_PROFILE``, then the default profile."""
    env = os.environ if env is None else env
    if cli_db and cli_profile:
        raise HabitlogError("use either --db or --profile, not both")
    if cli_db:
        return DbChoice(Path(cli_db).expanduser(), None, "--db")
    if cli_profile:
        name = check_profile_name(cli_profile).lower()
        return DbChoice(profile_db_path(name, env), name, "--profile")
    if env.get("HABITLOG_DB"):
        return DbChoice(Path(env["HABITLOG_DB"]).expanduser(), None, "HABITLOG_DB")
    if env.get("HABITLOG_PROFILE"):
        name = check_profile_name(env["HABITLOG_PROFILE"]).lower()
        return DbChoice(profile_db_path(name, env), name, "HABITLOG_PROFILE")
    return DbChoice(default_db_path(env), DEFAULT_PROFILE, "default")


def resolve_db_path(
    cli_value: str | None, env: Mapping[str, str] | None = None, profile: str | None = None
) -> Path:
    """Path of the database to open; see :func:`choose_db` for the order."""
    return choose_db(cli_value, profile, env).path


# --------------------------------------------------------------------------- connection


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open (creating parent directories and the schema as needed) a database."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _migrate_to_1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE habits (
            id       INTEGER PRIMARY KEY,
            name     TEXT    NOT NULL,
            name_key TEXT    NOT NULL UNIQUE,
            every    TEXT    NOT NULL CHECK (every IN ('daily', 'weekdays', 'weekly')),
            target   INTEGER NOT NULL CHECK (target >= 1),
            archived INTEGER NOT NULL DEFAULT 0,
            created  TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE completions (
            id        INTEGER PRIMARY KEY,
            habit_id  INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
            day       TEXT    NOT NULL,
            count     INTEGER NOT NULL CHECK (count >= 1),
            logged_at TEXT    NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_completions_habit_day ON completions (habit_id, day)")


def _migrate_to_2(conn: sqlite3.Connection) -> None:
    # An optional free-text note per completion row (``done --note``).
    conn.execute("ALTER TABLE completions ADD COLUMN note TEXT")


def _migrate_to_3(conn: sqlite3.Connection) -> None:
    # Date ranges (inclusive) during which a habit is paused (``habitlog pause``).
    conn.execute(
        """
        CREATE TABLE pauses (
            id        INTEGER PRIMARY KEY,
            habit_id  INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
            first_day TEXT    NOT NULL,
            last_day  TEXT    NOT NULL,
            CHECK (first_day <= last_day)
        )
        """
    )
    conn.execute("CREATE INDEX idx_pauses_habit ON pauses (habit_id, first_day)")


# Migration N upgrades a database from schema version N - 1 to N.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_to_1,
    2: _migrate_to_2,
    3: _migrate_to_3,
}


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0


def migrate(conn: sqlite3.Connection, target_version: int = SCHEMA_VERSION) -> int:
    """Bring the schema up to ``target_version``; each step runs in its own transaction."""
    current = get_schema_version(conn)
    if current > target_version:
        raise HabitlogError(
            f"database schema version {current} is newer than this habitlog supports "
            f"({target_version}); upgrade habitlog"
        )
    for version in range(current + 1, target_version + 1):
        with transaction(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            MIGRATIONS[version](conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )
    return get_schema_version(conn)


# --------------------------------------------------------------------------- habits


@dataclass(frozen=True)
class Habit:
    id: int
    name: str
    every: str
    target: int
    archived: bool
    created: date


def _row_to_habit(row: sqlite3.Row) -> Habit:
    return Habit(
        id=row["id"],
        name=row["name"],
        every=row["every"],
        target=row["target"],
        archived=bool(row["archived"]),
        created=date.fromisoformat(row["created"]),
    )


def name_key(name: str) -> str:
    return name.strip().casefold()


def clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise HabitlogError("habit name must not be empty")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise HabitlogError(f"habit name is longer than {MAX_NAME_LENGTH} characters")
    return cleaned


def clean_note(note: str) -> str:
    """Notes are single-line: runs of whitespace (including newlines) become one space."""
    cleaned = " ".join(note.split())
    if not cleaned:
        raise HabitlogError("note must not be empty")
    if len(cleaned) > MAX_NOTE_LENGTH:
        raise HabitlogError(f"note is longer than {MAX_NOTE_LENGTH} characters")
    return cleaned


def find_habit(conn: sqlite3.Connection, name: str) -> Habit | None:
    row = conn.execute(
        "SELECT * FROM habits WHERE name_key = ?", (name_key(" ".join(name.split())),)
    ).fetchone()
    return _row_to_habit(row) if row else None


def get_habit(conn: sqlite3.Connection, name: str) -> Habit:
    habit = find_habit(conn, name)
    if habit is None:
        raise HabitNotFound(f"no habit named '{name}'")
    return habit


def list_habits(conn: sqlite3.Connection, include_archived: bool = False) -> list[Habit]:
    sql = "SELECT * FROM habits"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY name_key"
    return [_row_to_habit(r) for r in conn.execute(sql)]


def add_habit(
    conn: sqlite3.Connection, name: str, every: str, target: int, created: date
) -> Habit:
    name = clean_name(name)
    if every not in FREQUENCIES:
        raise HabitlogError(f"unknown frequency '{every}'")
    if target < 1:
        raise HabitlogError("target must be at least 1")
    existing = find_habit(conn, name)
    if existing is not None:
        raise HabitlogError(f"habit '{existing.name}' already exists")
    with transaction(conn):
        conn.execute(
            "INSERT INTO habits (name, name_key, every, target, archived, created) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (name, name_key(name), every, target, created.isoformat()),
        )
    return get_habit(conn, name)


def rename_habit(conn: sqlite3.Connection, old: str, new: str) -> Habit:
    habit = get_habit(conn, old)
    new = clean_name(new)
    other = find_habit(conn, new)
    if other is not None and other.id != habit.id:
        raise HabitlogError(f"habit '{other.name}' already exists")
    with transaction(conn):
        conn.execute(
            "UPDATE habits SET name = ?, name_key = ? WHERE id = ?",
            (new, name_key(new), habit.id),
        )
    return get_habit(conn, new)


def update_habit(
    conn: sqlite3.Connection, habit: Habit, every: str | None = None, target: int | None = None
) -> Habit:
    """Change a habit's frequency and/or target; ``None`` keeps the current value.

    Only the habit row changes. Completions are never touched, so an edit is
    reversible: editing back restores the previous streaks exactly.
    """
    if every is not None and every not in FREQUENCIES:
        raise HabitlogError(f"unknown frequency '{every}'")
    if target is not None and target < 1:
        raise HabitlogError("target must be at least 1")
    with transaction(conn):
        conn.execute(
            "UPDATE habits SET every = ?, target = ? WHERE id = ?",
            (every or habit.every, habit.target if target is None else target, habit.id),
        )
    return get_habit(conn, habit.name)


def set_archived(conn: sqlite3.Connection, habit: Habit, archived: bool) -> None:
    with transaction(conn):
        conn.execute("UPDATE habits SET archived = ? WHERE id = ?", (int(archived), habit.id))


def remove_habit(conn: sqlite3.Connection, habit: Habit) -> int:
    """Delete a habit and its completions; returns how many completion rows went."""
    with transaction(conn):
        n = conn.execute(
            "SELECT COUNT(*) FROM completions WHERE habit_id = ?", (habit.id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM habits WHERE id = ?", (habit.id,))
    return n


# --------------------------------------------------------------------------- completions


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_completion(
    conn: sqlite3.Connection, habit: Habit, day: date, count: int = 1, note: str | None = None
) -> None:
    if count < 1:
        raise HabitlogError("count must be at least 1")
    if note is not None:
        note = clean_note(note)
    with transaction(conn):
        conn.execute(
            "INSERT INTO completions (habit_id, day, count, logged_at, note) VALUES (?, ?, ?, ?, ?)",
            (habit.id, day.isoformat(), count, _now(), note),
        )


def undo_completion(conn: sqlite3.Connection, habit: Habit, day: date) -> int:
    """Remove the most recently logged completion for ``day``; returns its count."""
    row = conn.execute(
        "SELECT id, count FROM completions WHERE habit_id = ? AND day = ? ORDER BY id DESC LIMIT 1",
        (habit.id, day.isoformat()),
    ).fetchone()
    if row is None:
        raise HabitlogError(f"nothing to undo for '{habit.name}' on {day.isoformat()}")
    with transaction(conn):
        conn.execute("DELETE FROM completions WHERE id = ?", (row["id"],))
    return int(row["count"])


def completion_counts(conn: sqlite3.Connection, habit: Habit) -> dict[date, int]:
    """Total count per day for one habit."""
    rows = conn.execute(
        "SELECT day, SUM(count) AS total FROM completions WHERE habit_id = ? GROUP BY day",
        (habit.id,),
    )
    return {date.fromisoformat(r["day"]): int(r["total"]) for r in rows}


def completion_notes(
    conn: sqlite3.Connection, habit: Habit, start: date | None = None, end: date | None = None
) -> list[tuple[date, str]]:
    """``(day, note)`` for completions that have a note, oldest first, optionally
    limited to ``start <= day <= end``."""
    sql = "SELECT day, note FROM completions WHERE habit_id = ? AND note IS NOT NULL"
    params: list[Any] = [habit.id]
    if start is not None:
        sql += " AND day >= ?"
        params.append(start.isoformat())
    if end is not None:
        sql += " AND day <= ?"
        params.append(end.isoformat())
    sql += " ORDER BY day, id"
    return [(date.fromisoformat(r["day"]), r["note"]) for r in conn.execute(sql, params)]


@dataclass(frozen=True)
class LogEntry:
    """One logged completion (a single ``done``), as stored."""

    day: date
    count: int
    note: str | None
    logged_at: str


def completion_log(
    conn: sqlite3.Connection,
    habit: Habit,
    since: date | None = None,
    limit: int | None = None,
) -> tuple[list[LogEntry], int]:
    """Logged completions of one habit, newest first (by day, then by when they
    were logged), optionally only those with ``day >= since``.

    Returns ``(entries, total)`` where ``entries`` holds at most ``limit`` rows
    and ``total`` is how many rows match without the limit.
    """
    where = "WHERE habit_id = ?"
    params: list[Any] = [habit.id]
    if since is not None:
        where += " AND day >= ?"
        params.append(since.isoformat())
    total = int(conn.execute(f"SELECT COUNT(*) FROM completions {where}", params).fetchone()[0])
    sql = f"SELECT day, count, note, logged_at FROM completions {where} ORDER BY day DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    entries = [
        LogEntry(date.fromisoformat(r["day"]), int(r["count"]), r["note"], r["logged_at"])
        for r in conn.execute(sql, params)
    ]
    return entries, total


# --------------------------------------------------------------------------- pauses


@dataclass(frozen=True)
class Pause:
    """An inclusive range of days during which a habit is paused."""

    first: date
    last: date

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


def list_pauses(conn: sqlite3.Connection, habit: Habit) -> list[Pause]:
    rows = conn.execute(
        "SELECT first_day, last_day FROM pauses WHERE habit_id = ? ORDER BY first_day",
        (habit.id,),
    )
    return [Pause(date.fromisoformat(r[0]), date.fromisoformat(r[1])) for r in rows]


def paused_days(conn: sqlite3.Connection, habit: Habit) -> frozenset[date]:
    """Every paused day of ``habit``, ready for the ``paused`` argument in ``streaks``."""
    days: set[date] = set()
    for p in list_pauses(conn, habit):
        days.update(p.first + timedelta(days=i) for i in range(p.days))
    return frozenset(days)


def _check_pause(first: date, last: date) -> None:
    if last < first:
        raise HabitlogError(
            f"pause ends ({last.isoformat()}) before it starts ({first.isoformat()})"
        )
    if (last - first).days + 1 > MAX_PAUSE_DAYS:
        raise HabitlogError(
            f"a pause can be at most {MAX_PAUSE_DAYS} days; archive the habit instead"
        )


def _merge_pause(conn: sqlite3.Connection, habit_id: int, first: date, last: date) -> Pause:
    """Store a pause, merging it with overlapping or adjacent ones (no transaction)."""
    one = timedelta(days=1)
    rows = conn.execute(
        "SELECT id, first_day, last_day FROM pauses "
        "WHERE habit_id = ? AND first_day <= ? AND last_day >= ?",
        (habit_id, (last + one).isoformat(), (first - one).isoformat()),
    ).fetchall()
    for r in rows:
        first = min(first, date.fromisoformat(r["first_day"]))
        last = max(last, date.fromisoformat(r["last_day"]))
        conn.execute("DELETE FROM pauses WHERE id = ?", (r["id"],))
    conn.execute(
        "INSERT INTO pauses (habit_id, first_day, last_day) VALUES (?, ?, ?)",
        (habit_id, first.isoformat(), last.isoformat()),
    )
    return Pause(first, last)


def add_pause(conn: sqlite3.Connection, habit: Habit, first: date, last: date) -> Pause:
    """Pause ``habit`` from ``first`` to ``last`` (inclusive).

    Overlapping or directly adjacent pauses are merged into one, so the stored
    ranges never overlap. Returns the resulting (possibly merged) pause.
    """
    _check_pause(first, last)
    with transaction(conn):
        return _merge_pause(conn, habit.id, first, last)


def end_pause(conn: sqlite3.Connection, habit: Habit, day: date) -> Pause | None:
    """End the pause that contains ``day`` or starts after it.

    A pause that began before ``day`` is cut short so its last day is the day
    before; one that starts on or after ``day`` is removed. Returns the pause
    as it was before the change, or ``None`` if there was nothing to end.
    """
    row = conn.execute(
        "SELECT id, first_day, last_day FROM pauses WHERE habit_id = ? AND last_day >= ? "
        "ORDER BY first_day LIMIT 1",
        (habit.id, day.isoformat()),
    ).fetchone()
    if row is None:
        return None
    old = Pause(date.fromisoformat(row["first_day"]), date.fromisoformat(row["last_day"]))
    with transaction(conn):
        if old.first < day:
            conn.execute(
                "UPDATE pauses SET last_day = ? WHERE id = ?",
                ((day - timedelta(days=1)).isoformat(), row["id"]),
            )
        else:
            conn.execute("DELETE FROM pauses WHERE id = ?", (row["id"],))
    return old


def clear_pauses(conn: sqlite3.Connection, habit: Habit) -> int:
    """Remove every pause of ``habit``; returns how many there were."""
    with transaction(conn):
        return conn.execute("DELETE FROM pauses WHERE habit_id = ?", (habit.id,)).rowcount


# --------------------------------------------------------------------------- export / import


def export_data(conn: sqlite3.Connection) -> dict[str, Any]:
    habits = []
    for h in list_habits(conn, include_archived=True):
        counts = completion_counts(conn, h)
        notes: dict[date, list[str]] = {}
        for d, note in completion_notes(conn, h):
            notes.setdefault(d, []).append(note)
        completions = []
        for d in sorted(counts):
            entry: dict[str, Any] = {"date": d.isoformat(), "count": counts[d]}
            if d in notes:
                entry["notes"] = notes[d]
            completions.append(entry)
        habit: dict[str, Any] = {
            "name": h.name,
            "every": h.every,
            "target": h.target,
            "archived": h.archived,
            "created": h.created.isoformat(),
            "completions": completions,
        }
        pauses = list_pauses(conn, h)
        if pauses:  # left out when empty, like a day's notes
            habit["pauses"] = [
                {"from": p.first.isoformat(), "to": p.last.isoformat()} for p in pauses
            ]
        habits.append(habit)
    return {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "habits": habits}


@dataclass(frozen=True)
class ImportResult:
    habits_created: int
    habits_existing: int
    completions_added: int
    notes_added: int = 0
    notes_skipped: int = 0
    pauses_added: int = 0
    # (habit name, setting, kept local value, differing imported value)
    conflicts: tuple[tuple[str, str, Any, Any], ...] = ()


def _validate_import(data: Any, today: date) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("habits"), list):
        raise HabitlogError("import file must be a JSON object with a 'habits' list")
    if data.get("format", EXPORT_FORMAT) != EXPORT_FORMAT:
        raise HabitlogError(f"unexpected format {data.get('format')!r}")
    version = data.get("version", EXPORT_VERSION)
    if not isinstance(version, int) or version > EXPORT_VERSION:
        raise HabitlogError(f"unsupported export version {version!r}")

    habits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, raw in enumerate(data["habits"]):
        where = f"habits[{i}]"
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
            raise HabitlogError(f"{where}: each habit needs a string 'name'")
        name = clean_name(raw["name"])
        if name_key(name) in seen:
            raise HabitlogError(f"{where}: duplicate habit '{name}'")
        seen.add(name_key(name))
        every = raw.get("every", "daily")
        if every not in FREQUENCIES:
            raise HabitlogError(f"{where}: unknown frequency {every!r}")
        target = raw.get("target", 1)
        if not isinstance(target, int) or isinstance(target, bool) or target < 1:
            raise HabitlogError(f"{where}: target must be a positive integer")
        archived = raw.get("archived", False)
        if not isinstance(archived, bool):
            raise HabitlogError(f"{where}: archived must be true or false")
        completions_raw = raw.get("completions", [])
        if not isinstance(completions_raw, list):
            raise HabitlogError(f"{where}: completions must be a list")
        counts: dict[date, int] = {}
        notes: dict[date, list[str]] = {}
        for j, c in enumerate(completions_raw):
            cwhere = f"{where}.completions[{j}]"
            if not isinstance(c, dict):
                raise HabitlogError(f"{cwhere}: expected an object with 'date' and 'count'")
            try:
                d = parse_date(c.get("date"))
            except ValueError as exc:
                raise HabitlogError(f"{cwhere}: {exc}") from None
            if d > today:
                raise HabitlogError(f"{cwhere}: {d.isoformat()} is in the future")
            n = c.get("count", 1)
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                raise HabitlogError(f"{cwhere}: count must be a positive integer")
            counts[d] = counts.get(d, 0) + n
            notes_raw = c.get("notes", [])
            if not isinstance(notes_raw, list) or not all(isinstance(x, str) for x in notes_raw):
                raise HabitlogError(f"{cwhere}: notes must be a list of strings")
            if len(notes_raw) > n:
                raise HabitlogError(f"{cwhere}: more notes than the count ({n})")
            try:
                notes.setdefault(d, []).extend(clean_note(x) for x in notes_raw)
            except HabitlogError as exc:
                raise HabitlogError(f"{cwhere}: {exc}") from None
        created_raw = raw.get("created")
        if created_raw is None:
            created = min(counts) if counts else today
        else:
            try:
                created = parse_date(created_raw)
            except ValueError as exc:
                raise HabitlogError(f"{where}: created: {exc}") from None
        pauses_raw = raw.get("pauses", [])  # absent in exports made before pauses existed
        if not isinstance(pauses_raw, list):
            raise HabitlogError(f"{where}: pauses must be a list")
        pauses: list[Pause] = []
        for j, p in enumerate(pauses_raw):
            pwhere = f"{where}.pauses[{j}]"
            if not isinstance(p, dict):
                raise HabitlogError(f"{pwhere}: expected an object with 'from' and 'to'")
            try:
                first, last = parse_date(p.get("from")), parse_date(p.get("to"))
                _check_pause(first, last)
            except (ValueError, HabitlogError) as exc:
                raise HabitlogError(f"{pwhere}: {exc}") from None
            pauses.append(Pause(first, last))
        habits.append(
            {
                "name": name,
                "every": every,
                "target": target,
                "archived": archived,
                "created": created,
                "counts": counts,
                "notes": notes,
                "pauses": pauses,
            }
        )
    return habits


def import_data(
    conn: sqlite3.Connection, data: Any, today: date, prefer: str = "local"
) -> ImportResult:
    """Merge an export into the database.

    Habits are matched by case-insensitive name; existing habits keep their own
    settings. For every day, completions are only added up to the imported
    total, so importing the same file twice changes nothing the second time.

    Notes merge the same way: an imported note the day doesn't already have is
    attached to one of that day's completions that has no note (existing ones
    first, then the ones this import adds). A note that finds no free
    completion (the day is fully logged and every completion already has a
    different note) is left out and counted in ``notes_skipped``.

    Pauses are merged with the habit's own (overlapping or adjacent ranges
    join); one already covered by an existing pause changes nothing and isn't
    counted in ``pauses_added``.

    When an existing habit's every/target/archived differ from the import,
    the local value is kept and the difference is listed in ``conflicts``.
    With ``prefer="file"`` the imported value replaces the local one instead
    (the differences are still listed, as (name, setting, old, new)).
    """
    if prefer not in ("local", "file"):
        raise HabitlogError(f"prefer must be 'local' or 'file', not {prefer!r}")
    habits = _validate_import(data, today)
    created = existing = added = notes_added = notes_skipped = pauses_added = 0
    conflicts: list[tuple[str, str, Any, Any]] = []
    with transaction(conn):
        for h in habits:
            row = conn.execute(
                "SELECT * FROM habits WHERE name_key = ?", (name_key(h["name"]),)
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO habits (name, name_key, every, target, archived, created) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        h["name"],
                        name_key(h["name"]),
                        h["every"],
                        h["target"],
                        int(h["archived"]),
                        h["created"].isoformat(),
                    ),
                )
                habit_id = cur.lastrowid
                created += 1
            else:
                habit_id = row["id"]
                existing += 1
                for field, local, theirs in (
                    ("every", row["every"], h["every"]),
                    ("target", row["target"], h["target"]),
                    ("archived", bool(row["archived"]), h["archived"]),
                ):
                    if local != theirs:
                        conflicts.append((row["name"], field, local, theirs))
                        if prefer == "file":
                            value = int(theirs) if field == "archived" else theirs
                            conn.execute(
                                f"UPDATE habits SET {field} = ? WHERE id = ?",  # field is a literal above
                                (value, habit_id),
                            )
            have = {
                r["day"]: int(r["total"])
                for r in conn.execute(
                    "SELECT day, SUM(count) AS total FROM completions WHERE habit_id = ? GROUP BY day",
                    (habit_id,),
                )
            }
            for d, n in sorted(h["counts"].items()):
                day = d.isoformat()
                rows = conn.execute(
                    "SELECT id, note FROM completions WHERE habit_id = ? AND day = ? ORDER BY id",
                    (habit_id, day),
                ).fetchall()
                pending = Counter(h["notes"].get(d, [])) - Counter(r["note"] for r in rows)
                new_notes = []
                for note in h["notes"].get(d, []):  # keep the imported order
                    if pending[note] > 0:
                        pending[note] -= 1
                        new_notes.append(note)
                for r in rows:
                    if not new_notes:
                        break
                    if r["note"] is None:
                        conn.execute(
                            "UPDATE completions SET note = ? WHERE id = ?",
                            (new_notes.pop(0), r["id"]),
                        )
                        notes_added += 1
                missing = n - have.get(day, 0)
                if missing > 0:
                    added += missing
                    # One row per remaining note (count 1 each; the last row takes the rest).
                    k = min(len(new_notes), missing)
                    chunks: list[tuple[int, str | None]] = [
                        (1, new_notes.pop(0)) for _ in range(k - 1)
                    ]
                    if k:
                        chunks.append((missing - (k - 1), new_notes.pop(0)))
                    else:
                        chunks.append((missing, None))
                    for count, note in chunks:
                        conn.execute(
                            "INSERT INTO completions (habit_id, day, count, logged_at, note) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (habit_id, day, count, _now(), note),
                        )
                        notes_added += note is not None
                notes_skipped += len(new_notes)
            for p in h["pauses"]:
                covered = conn.execute(
                    "SELECT 1 FROM pauses WHERE habit_id = ? AND first_day <= ? AND last_day >= ?",
                    (habit_id, p.first.isoformat(), p.last.isoformat()),
                ).fetchone()
                if covered is None:
                    _merge_pause(conn, habit_id, p.first, p.last)
                    pauses_added += 1
    return ImportResult(
        created, existing, added, notes_added, notes_skipped, pauses_added, tuple(conflicts)
    )

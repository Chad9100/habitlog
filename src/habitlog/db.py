"""SQLite storage, schema migrations and JSON import/export."""

from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .streaks import FREQUENCIES, parse_date

SCHEMA_VERSION = 1
EXPORT_FORMAT = "habitlog-export"
EXPORT_VERSION = 1
MAX_NAME_LENGTH = 100


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


def resolve_db_path(cli_value: str | None, env: Mapping[str, str] | None = None) -> Path:
    """``--db`` wins, then ``HABITLOG_DB``, then the per-user default."""
    env = os.environ if env is None else env
    if cli_value:
        return Path(cli_value).expanduser()
    if env.get("HABITLOG_DB"):
        return Path(env["HABITLOG_DB"]).expanduser()
    return default_db_path(env)


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


# Migration N upgrades a database from schema version N - 1 to N.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_to_1}


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


def add_completion(conn: sqlite3.Connection, habit: Habit, day: date, count: int = 1) -> None:
    if count < 1:
        raise HabitlogError("count must be at least 1")
    with transaction(conn):
        conn.execute(
            "INSERT INTO completions (habit_id, day, count, logged_at) VALUES (?, ?, ?, ?)",
            (habit.id, day.isoformat(), count, _now()),
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


# --------------------------------------------------------------------------- export / import


def export_data(conn: sqlite3.Connection) -> dict[str, Any]:
    habits = []
    for h in list_habits(conn, include_archived=True):
        counts = completion_counts(conn, h)
        habits.append(
            {
                "name": h.name,
                "every": h.every,
                "target": h.target,
                "archived": h.archived,
                "created": h.created.isoformat(),
                "completions": [
                    {"date": d.isoformat(), "count": counts[d]} for d in sorted(counts)
                ],
            }
        )
    return {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "habits": habits}


@dataclass(frozen=True)
class ImportResult:
    habits_created: int
    habits_existing: int
    completions_added: int


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
        created_raw = raw.get("created")
        if created_raw is None:
            created = min(counts) if counts else today
        else:
            try:
                created = parse_date(created_raw)
            except ValueError as exc:
                raise HabitlogError(f"{where}: created: {exc}") from None
        habits.append(
            {
                "name": name,
                "every": every,
                "target": target,
                "archived": archived,
                "created": created,
                "counts": counts,
            }
        )
    return habits


def import_data(conn: sqlite3.Connection, data: Any, today: date) -> ImportResult:
    """Merge an export into the database.

    Habits are matched by case-insensitive name; existing habits keep their own
    settings. For every day, completions are only added up to the imported
    total, so importing the same file twice changes nothing the second time.
    """
    habits = _validate_import(data, today)
    created = existing = added = 0
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
            have = {
                r["day"]: int(r["total"])
                for r in conn.execute(
                    "SELECT day, SUM(count) AS total FROM completions WHERE habit_id = ? GROUP BY day",
                    (habit_id,),
                )
            }
            for d, n in sorted(h["counts"].items()):
                missing = n - have.get(d.isoformat(), 0)
                if missing > 0:
                    conn.execute(
                        "INSERT INTO completions (habit_id, day, count, logged_at) VALUES (?, ?, ?, ?)",
                        (habit_id, d.isoformat(), missing, _now()),
                    )
                    added += missing
    return ImportResult(created, existing, added)

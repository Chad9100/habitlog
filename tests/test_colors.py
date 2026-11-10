from __future__ import annotations

import io
import re
from datetime import date

import pytest

from habitlog import colors
from habitlog.cli import main
from habitlog.heatmap import legend, month_grid, month_strip, render

WED = date(2026, 3, 4)
ANSI = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


class FakeTTY(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        if self.closed:  # like real streams
            raise ValueError("I/O operation on closed file")
        return self._tty


# --------------------------------------------------------------------------- use_color


@pytest.mark.parametrize("tty", [True, False])
def test_always_and_never_ignore_terminal_and_env(tty):
    env = {"NO_COLOR": "1", "TERM": "dumb"}
    assert colors.use_color("always", FakeTTY(tty), env) is True
    assert colors.use_color("never", FakeTTY(tty), env) is False


def test_auto_is_off_when_not_a_terminal():
    assert colors.use_color("auto", FakeTTY(False), {}) is False
    assert colors.use_color("auto", io.StringIO(), {}) is False


def test_auto_respects_no_color_and_dumb_terminal():
    assert colors.use_color("auto", FakeTTY(True), {"NO_COLOR": "1"}) is False
    assert colors.use_color("auto", FakeTTY(True), {"TERM": "dumb"}) is False


def test_auto_on_a_terminal(monkeypatch):
    monkeypatch.setattr(colors, "_enable_windows_vt", lambda: True)
    assert colors.use_color("auto", FakeTTY(True), {}) is True
    # An empty NO_COLOR does not disable colour (no-color.org).
    assert colors.use_color("auto", FakeTTY(True), {"NO_COLOR": ""}) is True


def test_auto_off_when_windows_console_refuses_ansi(monkeypatch):
    monkeypatch.setattr(colors.sys, "platform", "win32")
    monkeypatch.setattr(colors, "_enable_windows_vt", lambda: False)
    assert colors.use_color("auto", FakeTTY(True), {}) is False


def test_closed_stream_means_no_colour(monkeypatch):
    monkeypatch.setattr(colors, "_enable_windows_vt", lambda: True)
    stream = FakeTTY(True)
    stream.close()
    assert colors.use_color("auto", stream, {}) is False


def test_invalid_mode():
    with pytest.raises(ValueError):
        colors.use_color("sometimes", FakeTTY(True), {})


def test_paint_leaves_blank_text_alone():
    assert colors.paint("x", "32") == "\033[32mx\033[0m"
    assert colors.paint(" ", "32") == " "
    assert colors.paint("x", "") == "x"


# --------------------------------------------------------------------------- rendering


def test_coloured_heatmap_has_same_layout():
    counts = {date(2026, 2, d): d % 4 for d in range(1, 29)}
    for compact in (False, True):
        plain = render(counts, 3, WED, weeks=8, compact=compact)
        coloured = render(counts, 3, WED, weeks=8, compact=compact, color=True)
        assert coloured != plain
        assert [strip_ansi(line) for line in coloured] == plain


def test_shades_get_their_level_colour():
    lines = render({WED: 1}, 1, WED, weeks=2, ascii=True, color=True)
    assert lines[3] == "Wed \033[90m.\033[0m \033[1;32m#\033[0m"
    # Future days stay uncoloured blanks, so trailing space is still stripped.
    assert lines[4] == "Thu \033[90m.\033[0m"


def test_month_views_and_legend_colour():
    month = date(2026, 3, 1)
    plain = month_grid({WED: 2}, 1, month, WED, ascii=True)
    coloured = month_grid({WED: 2}, 1, month, WED, ascii=True, color=True)
    assert [strip_ansi(line) for line in coloured] == plain
    strip = month_strip({WED: 1}, 1, month, WED, ascii=True, color=True)
    assert strip_ansi(strip) == month_strip({WED: 1}, 1, month, WED, ascii=True)
    assert "\033[1;32m#\033[0m" in strip
    assert strip_ansi(legend(color=True)) == legend()


# --------------------------------------------------------------------------- CLI


def run(capsys, db, *argv, today=WED):
    code = main(["--db", str(db), *argv], today=today)
    out = capsys.readouterr().out
    assert code == 0
    return out


@pytest.fixture
def db(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HABITLOG_DB", str(tmp_path / "unused.db"))
    path = tmp_path / "habits.db"
    main(["--db", str(path), "add", "Read"], today=date(2026, 2, 1))
    main(["--db", str(path), "add", "Water", "--target", "8"], today=date(2026, 2, 1))
    main(["--db", str(path), "add", "Gym"], today=date(2026, 2, 1))
    main(["--db", str(path), "done", "Read"], today=WED)
    main(["--db", str(path), "done", "Water", "--count", "3"], today=WED)
    capsys.readouterr()
    return path


def test_output_is_plain_by_default_when_captured(capsys, db):
    out = run(capsys, db, "stats", "Read")
    assert "\033[" not in out
    assert "\033[" not in run(capsys, db, "list")


def test_color_always_on_stats_and_month(capsys, db):
    plain = run(capsys, db, "stats", "Read", "--color", "never")
    coloured = run(capsys, db, "stats", "Read", "--color", "always")
    assert "\033[" in coloured
    assert strip_ansi(coloured) == plain
    plain = run(capsys, db, "month", "--color=never")
    coloured = run(capsys, db, "--color", "always", "month")  # also before the command
    assert "\033[" in coloured
    assert strip_ansi(coloured) == plain


def test_list_colours_today_column_and_keeps_alignment(capsys, db):
    plain = run(capsys, db, "list")
    coloured = run(capsys, db, "list", "--color", "always")
    assert strip_ansi(coloured) == plain
    lines = coloured.splitlines()
    read = next(line for line in lines if line.startswith("Read"))
    water = next(line for line in lines if line.startswith("Water"))
    gym = next(line for line in lines if line.startswith("Gym"))
    assert "\033[1;32mdone\033[0m" in read
    assert "\033[33m3/8\033[0m" in water
    assert "\033[" not in gym  # nothing logged yet: left plain


def test_json_is_never_coloured(capsys, db):
    out = run(capsys, db, "stats", "Read", "--json", "--color", "always")
    assert "\033[" not in out


def test_invalid_color_value_is_a_usage_error(capsys, db):
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(db), "list", "--color", "rainbow"], today=WED)
    assert exc.value.code == 2

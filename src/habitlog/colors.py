"""Optional ANSI colour for terminal output.

Colour is decided once per run by :func:`use_color` from ``--color`` and the
environment, then passed down explicitly; the rendering code never looks at
the terminal itself, so it stays pure and easy to test.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping, TextIO

WHEN_CHOICES = ("auto", "always", "never")

RESET = "\033[0m"
# Heatmap shades by level (0 none .. 3 target met): grey, then three greens.
SHADE_STYLES = ("90", "2;32", "32", "1;32")
# list TODAY column.
STATUS_STYLES = {"done": "1;32", "rest": "90", "partial": "33", "paused": "36"}


def paint(text: str, style: str | None) -> str:
    """Wrap ``text`` in an ANSI SGR sequence; blank text or no style is left as is."""
    if not style or not text.strip():
        return text
    return f"\033[{style}m{text}{RESET}"


def use_color(
    when: str = "auto",
    stream: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Whether to colour output written to ``stream`` (default: stdout).

    ``always`` and ``never`` are taken literally. ``auto`` colours only when the
    stream is a terminal, ``NO_COLOR`` is unset or empty (https://no-color.org),
    ``TERM`` is not ``dumb``, and, on Windows, the console accepts ANSI escapes.
    """
    if when not in WHEN_CHOICES:
        raise ValueError(f"invalid colour mode {when!r}")
    if when != "auto":
        return when == "always"
    env = os.environ if environ is None else environ
    if env.get("NO_COLOR"):
        return False
    if env.get("TERM") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    isatty = getattr(stream, "isatty", None)
    try:
        if isatty is None or not isatty():
            return False
    except (ValueError, OSError):  # closed or detached stream
        return False
    if sys.platform == "win32":
        return _enable_windows_vt()
    return True


def _enable_windows_vt() -> bool:  # pragma: no cover - needs a real Windows console
    """Turn on ANSI escape processing for the console; False if it can't be done."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if mode.value & enable_vt:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except (AttributeError, OSError):
        return False

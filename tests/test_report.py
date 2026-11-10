"""`habitlog report --html` and the pure HTML renderer."""

from __future__ import annotations

from datetime import date, timedelta
from html.parser import HTMLParser

import pytest

from habitlog import report
from habitlog.streaks import Rate

# The `run` fixture uses Wednesday 2026-03-04 as today.
TODAY = date(2026, 3, 4)


class _Collector(HTMLParser):
    """Collects heatmap cells (class -> title text), tags and table rows."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: dict[str, str] = {}  # date -> class
        self.titles: dict[str, str] = {}  # date -> full tooltip
        self.tags: list[str] = []
        self.rows: list[list[str]] = []
        self.sections: list[str] = []
        self._rect_class: str | None = None
        self._in_title = False
        self._title = ""
        self._row: list[str] | None = None
        self._cell: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        if tag == "rect" and a.get("x") not in (None, "0.5"):  # heatmap cell, not legend
            self._rect_class = a.get("class")
        elif tag == "title" and self._rect_class is not None:
            self._in_title, self._title = True, ""
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = ""
        elif tag == "section":
            self.sections.append(a["id"])

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            day = self._title.split(":")[0].split()[1]
            self.cells[day] = self._rect_class
            self.titles[day] = self._title
            self._in_title, self._rect_class = False, None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(self._cell.strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_title:
            self._title += data
        if self._cell is not None:
            self._cell += data


def parse(text: str) -> _Collector:
    c = _Collector()
    c.feed(text)
    c.close()
    return c


def _habit(**kw) -> report.HabitReport:
    base = dict(
        name="Read", every="daily", target=1, archived=False, counts={},
        rate=Rate(TODAY, TODAY, 0, 0), current_streak=0, longest_streak=0,
    )
    base.update(kw)
    return report.HabitReport(**base)


# --------------------------------------------------------------------------- pure renderer


def test_window_starts_on_monday_and_covers_requested_weeks():
    first = report.window_start(TODAY, 53)
    assert first.weekday() == 0
    assert first == date(2025, 3, 3)  # 52 weeks before Monday 2026-03-02
    with pytest.raises(ValueError):
        report.window_start(TODAY, 0)


def test_heatmap_has_one_cell_per_day_up_to_today():
    c = parse(report.heatmap_svg(_habit(), TODAY, 2))
    # Mon 23 Feb .. Wed 4 Mar: 7 + 3 days, nothing after today.
    assert len(c.cells) == 10
    assert min(c.cells) == "2026-02-23" and max(c.cells) == "2026-03-04"


def test_heatmap_shading_follows_daily_target_and_shows_notes():
    h = _habit(
        name="Water", target=4,
        counts={date(2026, 3, 2): 1, date(2026, 3, 3): 2, TODAY: 5},
        notes={TODAY: ["after run", "a <b> & c"]},
    )
    c = parse(report.heatmap_svg(h, TODAY, 1))
    assert c.cells["2026-03-02"] == "l1"
    assert c.cells["2026-03-03"] == "l2"
    assert c.cells["2026-03-04"] == "l3"
    assert c.titles["2026-03-04"] == "Wed 2026-03-04: 5/4\n- after run\n- a <b> & c"
    assert c.titles["2026-03-02"] == "Mon 2026-03-02: 1/4"


def test_weekly_habit_shades_each_day_against_one():
    h = _habit(every="weekly", target=3, counts={date(2026, 3, 2): 1})
    c = parse(report.heatmap_svg(h, TODAY, 1))
    assert c.cells["2026-03-02"] == "l3"
    assert c.titles["2026-03-02"] == "Mon 2026-03-02: 1"


def test_weekdays_habit_marks_empty_weekends_as_rest_days():
    h = _habit(every="weekdays", counts={date(2026, 2, 28): 1})  # Saturday, logged anyway
    c = parse(report.heatmap_svg(h, TODAY, 2))
    assert c.cells["2026-02-28"] == "l3"
    assert c.cells["2026-03-01"] == "off"  # Sunday, nothing logged
    assert c.cells["2026-02-27"] == "l0"  # Friday, missed


def test_month_labels_name_each_new_month():
    svg = report.heatmap_svg(_habit(), TODAY, 53)
    assert ">Mar 2025<" in svg and ">Jan 2026<" in svg
    for month in ("Apr", "Jun", "Sep", "Dec"):
        assert f">{month}<" in svg


def test_render_html_is_self_contained_and_escapes_names():
    h = _habit(
        name='<script>alert("x")</script>', archived=True,
        counts={date(2026, 3, 1): 2, TODAY: 1, date(2024, 1, 1): 1},
        rate=Rate(date(2025, 3, 3), TODAY, 10, 7), current_streak=4, longest_streak=9,
    )
    text = report.render_html([h], TODAY, 53, title="Q1 & more")
    c = parse(text)
    assert "script" not in c.tags and "link" not in c.tags and "img" not in c.tags
    assert "http://" not in text and "https://" not in text
    assert "<title>Q1 &amp; more</title>" in text
    assert c.rows[0][0] == "Habit"
    assert c.rows[1] == [
        '<script>alert("x")</script> (archived)', "daily", "1",
        "4 days", "9 days", "7/10", "70%", "3", "2026-03-04",
    ]
    assert c.sections == ["habit-1"]
    # The legend's weekend swatch only appears when a weekdays habit is shown.
    assert "not counted for weekdays habits" not in text


def test_rate_without_periods_is_na_and_never_done_shows_dash():
    c = parse(report.render_html([_habit()], TODAY, 4))
    assert c.rows[1][5:] == ["0/0", "n/a", "0", "-"]


# --------------------------------------------------------------------------- CLI


@pytest.fixture
def habits(run):
    assert run("add", "Read").code == 0
    assert run("add", "Gym", "--every", "weekly", "--target", "2").code == 0
    assert run("add", "Old").code == 0
    for i in range(5):  # Sat 28 Feb .. Wed 4 Mar
        d = (TODAY - timedelta(days=i)).isoformat()
        assert run("done", "Read", "--date", d).code == 0
    assert run("done", "Read", "--note", "ch. 3").code == 0
    assert run("done", "Gym", "--date", "2026-03-02").code == 0
    assert run("done", "Old", "--date", "2026-03-01").code == 0
    assert run("archive", "Old").code == 0
    return run


def test_report_writes_file_with_summary_and_heatmaps(habits, tmp_path):
    out = tmp_path / "report.html"
    r = habits("report", "--html", str(out))
    assert r.code == 0, r.err
    assert r.out == f"Wrote a report of 2 habits over 53 weeks to {out}.\n"
    c = parse(out.read_text(encoding="utf-8"))
    by_name = {row[0]: row for row in c.rows[1:]}
    assert set(by_name) == {"Read", "Gym"}
    # Read: done every day since Sat 28 Feb (today twice); started 4 Mar per `add`,
    # so the rate counts from the first completion.
    assert by_name["Read"][3:] == ["5 days", "5 days", "5/5", "100%", "6", "2026-03-04"]
    assert by_name["Gym"][3:] == ["0 weeks", "0 weeks", "0/0", "n/a", "1", "2026-03-02"]
    assert c.sections == ["habit-1", "habit-2"]
    assert "Wed 2026-03-04: 2\n- ch. 3" in c.titles.values()


def test_report_all_includes_archived_and_stdout_mode(habits):
    r = habits("report", "--html", "-", "--all", "--weeks", "2", "--title", "Me")
    assert r.code == 0, r.err
    assert r.out.startswith("<!doctype html>")
    c = parse(r.out)
    assert [row[0] for row in c.rows[1:]] == ["Gym", "Old (archived)", "Read"]
    assert "last 2 weeks (2026-02-23 to 2026-03-04)" in r.out
    assert "<h1>Me</h1>" in r.out


def test_report_errors(run, tmp_path):
    assert run("report").code == 2  # --html is required
    r = run("report", "--html", str(tmp_path / "x.html"))
    assert r.code == 1 and "no habits to report on" in r.err and "--all" not in r.err
    run("add", "Read")
    run("archive", "Read")
    r = run("report", "--html", "-")
    assert r.code == 1 and "need --all" in r.err
    r = run("report", "--html", str(tmp_path / "missing" / "dir" / "x.html"), "--all")
    assert r.code == 1 and "cannot write" in r.err
    assert run("report", "--html", "-", "--weeks", "0").code == 2

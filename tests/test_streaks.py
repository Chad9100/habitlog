from __future__ import annotations

from datetime import date, timedelta

import pytest

from habitlog.streaks import (
    completion_rate,
    current_streak,
    iter_periods,
    longest_streak,
    open_period,
    parse_date,
    period_totals,
    previous_period,
    today_progress,
    week_start,
)

D = date.fromisoformat
WED = D("2026-03-04")  # Wednesday
MON = D("2026-03-02")
FRI = D("2026-03-06")
SAT = D("2026-03-07")
SUN = D("2026-03-08")


def days(*isos: str, count: int = 1) -> dict[date, int]:
    return {D(s): count for s in isos}


def run_of(end: date, n: int, count: int = 1) -> dict[date, int]:
    return {end - timedelta(days=i): count for i in range(n)}


def test_fixture_weekdays_are_what_the_tests_assume():
    assert (MON.weekday(), WED.weekday(), FRI.weekday(), SAT.weekday(), SUN.weekday()) == (
        0, 2, 4, 5, 6,
    )


# --------------------------------------------------------------------------- parsing


@pytest.mark.parametrize("text", ["2026-3-4", "20260304", "2026/03/04", "2026-02-30", "", "today"])
def test_parse_date_rejects_non_iso(text):
    with pytest.raises(ValueError):
        parse_date(text)


def test_parse_date_accepts_iso_with_spaces():
    assert parse_date(" 2026-03-04 ") == WED


# --------------------------------------------------------------------------- daily


def test_daily_no_completions_is_zero():
    assert current_streak({}, "daily", 1, WED) == 0
    assert longest_streak({}, "daily", 1, WED) == 0


def test_daily_streak_including_today():
    assert current_streak(run_of(WED, 5), "daily", 1, WED) == 5


def test_daily_today_not_done_yet_keeps_streak():
    counts = run_of(WED - timedelta(days=1), 4)
    assert current_streak(counts, "daily", 1, WED) == 4


def test_daily_yesterday_missed_breaks_streak():
    counts = run_of(WED - timedelta(days=2), 4)
    assert current_streak(counts, "daily", 1, WED) == 0


def test_daily_done_today_after_missing_yesterday_is_one():
    counts = run_of(WED - timedelta(days=2), 4)
    counts[WED] = 1
    assert current_streak(counts, "daily", 1, WED) == 1


def test_daily_gap_splits_runs_and_longest_picks_biggest():
    counts = days("2026-02-01", "2026-02-02", "2026-02-03", "2026-02-05", "2026-03-03", "2026-03-04")
    assert current_streak(counts, "daily", 1, WED) == 2
    assert longest_streak(counts, "daily", 1, WED) == 3


def test_daily_target_above_one_needs_full_count():
    counts = {D("2026-03-01"): 2, D("2026-03-02"): 1, D("2026-03-03"): 2}
    assert current_streak(counts, "daily", 2, WED) == 1
    assert longest_streak(counts, "daily", 2, WED) == 1


def test_daily_partial_today_does_not_break_streak():
    counts = {D("2026-03-02"): 3, D("2026-03-03"): 3, WED: 1}
    assert current_streak(counts, "daily", 3, WED) == 2


def test_daily_extra_count_beyond_target_still_one_period():
    assert current_streak({WED: 5}, "daily", 1, WED) == 1


def test_longest_ignores_entries_after_today():
    counts = run_of(D("2026-03-10"), 10)  # 1..10 March
    assert longest_streak(counts, "daily", 1, WED) == 4


def test_longest_at_least_current():
    counts = run_of(WED, 7)
    assert longest_streak(counts, "daily", 1, WED) >= current_streak(counts, "daily", 1, WED)


def test_daily_streak_across_month_and_leap_day():
    counts = run_of(D("2024-03-01"), 3)  # 28 Feb, 29 Feb, 1 Mar 2024
    assert current_streak(counts, "daily", 1, D("2024-03-01")) == 3


# --------------------------------------------------------------------------- weekdays


def test_weekdays_streak_spans_weekend():
    counts = days("2026-02-26", "2026-02-27", "2026-03-02", "2026-03-03", "2026-03-04")  # Thu..Wed
    assert current_streak(counts, "weekdays", 1, WED) == 5


def test_weekdays_saturday_counts_through_friday():
    counts = days("2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06")
    assert current_streak(counts, "weekdays", 1, SAT) == 5
    assert current_streak(counts, "weekdays", 1, SUN) == 5


def test_weekdays_monday_open_counts_back_to_friday():
    counts = days("2026-03-05", "2026-03-06")  # Thu, Fri
    assert current_streak(counts, "weekdays", 1, D("2026-03-09")) == 2


def test_weekdays_weekend_completions_neither_extend_nor_break():
    counts = days("2026-03-06", "2026-03-07", "2026-03-08", "2026-03-09")  # Fri Sat Sun Mon
    assert current_streak(counts, "weekdays", 1, D("2026-03-09")) == 2
    assert longest_streak(counts, "weekdays", 1, D("2026-03-09")) == 2


def test_weekdays_missed_weekday_breaks():
    counts = days("2026-03-02", "2026-03-04")  # Mon, Wed (Tue missed)
    assert current_streak(counts, "weekdays", 1, WED) == 1


def test_weekdays_missed_friday_breaks_after_weekend():
    counts = days("2026-03-05", "2026-03-09")  # Thu, Mon
    assert current_streak(counts, "weekdays", 1, D("2026-03-09")) == 1


def test_weekdays_only_weekend_activity_is_zero():
    counts = days("2026-03-07", "2026-03-08")
    assert current_streak(counts, "weekdays", 1, SUN) == 0
    assert longest_streak(counts, "weekdays", 1, SUN) == 0


def test_previous_period_weekdays_skips_weekend():
    assert previous_period(D("2026-03-09"), "weekdays") == FRI
    assert previous_period(SUN, "weekdays") == FRI
    assert previous_period(WED, "weekdays") == D("2026-03-03")


# --------------------------------------------------------------------------- weekly


def test_week_start_is_monday():
    assert week_start(WED) == MON
    assert week_start(SUN) == MON
    assert week_start(MON) == MON


def test_weekly_open_week_counts_previous_weeks():
    counts = days("2026-02-17", "2026-02-25")  # two previous weeks
    assert current_streak(counts, "weekly", 1, WED) == 2


def test_weekly_done_this_week_extends():
    counts = days("2026-02-17", "2026-02-25", "2026-03-02")
    assert current_streak(counts, "weekly", 1, WED) == 3


def test_weekly_missed_week_breaks():
    counts = days("2026-02-10", "2026-02-25")  # week of 9 Feb, skip 16 Feb, week of 23 Feb
    assert current_streak(counts, "weekly", 1, WED) == 1
    assert longest_streak(counts, "weekly", 1, WED) == 1


def test_weekly_target_sums_days_within_iso_week():
    counts = days("2026-02-23", "2026-02-25", "2026-03-01")  # Mon, Wed, Sun of one week
    assert current_streak(counts, "weekly", 3, WED) == 1


def test_weekly_target_not_split_across_weeks():
    counts = days("2026-02-28", "2026-03-01", "2026-03-02")  # Sat, Sun | Mon
    assert period_totals(counts, "weekly") == {D("2026-02-23"): 2, MON: 1}
    assert current_streak(counts, "weekly", 3, WED) == 0


def test_weekly_partial_current_week_is_open_not_broken():
    counts = {D("2026-02-24"): 3, MON: 1}
    assert current_streak(counts, "weekly", 3, WED) == 1


def test_weekly_across_year_boundary_with_iso_week_53():
    # 2020 has ISO week 53 (Mon 28 Dec 2020); next is 2021-W01 (Mon 4 Jan 2021).
    counts = days("2020-12-23", "2020-12-31", "2021-01-05")
    assert current_streak(counts, "weekly", 1, D("2021-01-06")) == 3


def test_weekly_iso_week_spanning_new_year_is_one_period():
    # Mon 29 Dec 2025 .. Sun 4 Jan 2026 is ISO week 2026-W01.
    counts = days("2025-12-30", "2026-01-02")
    assert period_totals(counts, "weekly") == {D("2025-12-29"): 2}
    assert current_streak(counts, "weekly", 2, D("2026-01-08")) == 1


def test_weekly_longest_across_year_boundary():
    counts = days("2025-12-15", "2025-12-22", "2025-12-29", "2026-01-05", "2026-02-02")
    assert longest_streak(counts, "weekly", 1, WED) == 4
    assert current_streak(counts, "weekly", 1, WED) == 0


# --------------------------------------------------------------------------- progress


def test_today_progress_states():
    assert today_progress({}, "daily", 1, WED).status == "open"
    assert today_progress({WED: 1}, "daily", 2, WED).status == "partial"
    assert today_progress({WED: 2}, "daily", 2, WED).status == "done"
    assert today_progress({WED: 1}, "weekdays", 1, SAT).status == "rest"


def test_today_progress_weekly_counts_whole_week():
    p = today_progress(days("2026-03-02", "2026-03-03"), "weekly", 3, WED)
    assert (p.period_count, p.status) == (2, "partial")


def test_open_period():
    assert open_period(SAT, "weekdays") is None
    assert open_period(SAT, "weekly") == MON
    assert open_period(SAT, "daily") == SAT


# --------------------------------------------------------------------------- rates


def test_iter_periods_kinds():
    assert len(list(iter_periods(MON, SUN, "daily"))) == 7
    assert len(list(iter_periods(MON, SUN, "weekdays"))) == 5
    assert list(iter_periods(WED, D("2026-03-16"), "weekly")) == [MON, D("2026-03-09"), D("2026-03-16")]


def test_rate_daily_excludes_open_today():
    counts = days("2026-03-02", "2026-03-03")
    r = completion_rate(counts, "daily", 1, WED, weeks=1)
    assert (r.periods_met, r.periods_total) == (2, 2)
    assert r.rate == 1.0


def test_rate_daily_includes_today_once_done():
    counts = days("2026-03-02", "2026-03-04")
    r = completion_rate(counts, "daily", 1, WED, weeks=1)
    assert (r.periods_met, r.periods_total) == (2, 3)


def test_rate_since_clamps_window_start():
    r = completion_rate({}, "daily", 1, WED, weeks=12, since=D("2026-03-03"))
    assert r.start == D("2026-03-03")
    assert r.periods_total == 1
    assert r.rate == 0.0


def test_rate_weekdays_skip_weekends():
    counts = days("2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27", "2026-02-28")
    r = completion_rate(counts, "weekdays", 1, SUN, weeks=2)
    assert (r.periods_met, r.periods_total) == (5, 10)


def test_rate_weekly_counts_weeks():
    counts = days("2026-02-17", "2026-02-25")
    r = completion_rate(counts, "weekly", 1, WED, weeks=4)
    assert (r.periods_met, r.periods_total) == (2, 3)


def test_rate_with_no_periods_is_none():
    r = completion_rate({}, "daily", 1, WED, weeks=1, since=WED)
    assert r.periods_total == 0 and r.rate is None


def test_rate_rejects_zero_weeks():
    with pytest.raises(ValueError):
        completion_rate({}, "daily", 1, WED, weeks=0)


def test_unknown_frequency_is_rejected():
    with pytest.raises(ValueError):
        current_streak({}, "monthly", 1, WED)

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.consumption import bucketize, consumption_delta, hour_floor, window

MNL = ZoneInfo("Asia/Manila")
BER = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 6, 10, 58, tzinfo=MNL)


def local(y, m, d, h=0, tz=MNL):
    return datetime(y, m, d, h, tzinfo=tz)


def test_first_reading_is_baseline():
    assert consumption_delta(None, 100.0, "ok") == 0.0


def test_delta_between_readings():
    assert consumption_delta(100.0, 102.5, "ok") == 2.5


def test_reset_is_baseline():
    assert consumption_delta(102.5, 3.0, "reset") == 0.0


def test_negative_delta_dropped():
    assert consumption_delta(102.5, 102.0, "ok") == 0.0


def test_hour_floor():
    assert hour_floor(7200 + 59 * 60 + 59) == 7200
    assert hour_floor(7200) == 7200


def test_hour_window_today():
    w = window("hour", date(2026, 10, 6), MNL, NOW)
    assert w.start == local(2026, 10, 6)
    assert w.end == local(2026, 10, 7)
    assert len(w.buckets) == 24
    assert w.buckets[13] == local(2026, 10, 6, 13)
    assert w.prev_anchor == date(2026, 10, 5)
    assert w.next_anchor is None


def test_hour_window_past_has_next():
    w = window("hour", date(2026, 10, 5), MNL, NOW)
    assert w.next_anchor == date(2026, 10, 6)


def test_hour_window_dst_days():
    now = datetime(2026, 12, 1, tzinfo=BER)
    assert len(window("hour", date(2026, 3, 29), BER, now).buckets) == 23
    assert len(window("hour", date(2026, 10, 25), BER, now).buckets) == 25
    assert len(window("hour", date(2026, 10, 26), BER, now).buckets) == 24


def test_day_window():
    w = window("day", date(2026, 2, 10), MNL, NOW)
    assert w.start == local(2026, 2, 1)
    assert w.end == local(2026, 3, 1)
    assert len(w.buckets) == 28
    assert w.buckets[9] == local(2026, 2, 10)
    assert w.prev_anchor == date(2026, 1, 31)
    assert w.next_anchor == date(2026, 3, 1)


def test_day_window_leap_year():
    assert len(window("day", date(2028, 2, 10), MNL, NOW).buckets) == 29


def test_week_window_current():
    w = window("week", date(2026, 10, 6), MNL, NOW)
    assert w.start == local(2026, 7, 20)
    assert w.end == local(2026, 10, 12)
    assert len(w.buckets) == 12
    assert w.buckets[0] == local(2026, 7, 20)
    assert w.buckets[11] == local(2026, 10, 5)
    assert all(b.weekday() == 0 for b in w.buckets)
    assert w.prev_anchor == date(2026, 7, 19)
    assert w.next_anchor is None


def test_week_window_past_next_is_contiguous():
    w = window("week", date(2026, 7, 1), MNL, NOW)
    assert w.start == local(2026, 4, 13)
    assert w.end == local(2026, 7, 6)
    assert w.next_anchor == date(2026, 9, 21)
    assert window("week", w.next_anchor, MNL, NOW).start == w.end
    assert window("week", w.prev_anchor, MNL, NOW).end == w.start


def test_month_window():
    w = window("month", date(2026, 10, 6), MNL, NOW)
    assert w.start == local(2026, 1, 1)
    assert w.end == local(2027, 1, 1)
    assert len(w.buckets) == 12
    assert w.buckets[9] == local(2026, 10, 1)
    assert w.prev_anchor == date(2025, 12, 31)
    assert w.next_anchor is None


def test_year_window():
    w = window("year", date(2026, 10, 6), MNL, NOW, first_year=2024)
    assert w.buckets == [local(2024, 1, 1), local(2025, 1, 1), local(2026, 1, 1)]
    assert w.start == local(2024, 1, 1)
    assert w.end == local(2027, 1, 1)
    assert w.prev_anchor is None
    assert w.next_anchor is None


def test_year_window_without_data():
    w = window("year", date(2026, 10, 6), MNL, NOW, first_year=None)
    assert w.buckets == [local(2026, 1, 1)]


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        window("minute", date(2026, 10, 6), MNL, NOW)


def test_bucketize_gaps_zero_and_outside():
    w = window("hour", date(2026, 10, 6), MNL, NOW)

    def ts(dt):
        return int(dt.timestamp())

    hourly = {
        ts(local(2026, 10, 6, 0)): 0.5,
        ts(local(2026, 10, 6, 13)): 0.0,
        ts(local(2026, 10, 5, 23)): 9.0,
        ts(local(2026, 10, 7, 0)): 9.0,
    }
    values = bucketize(hourly, w)
    assert len(values) == 24
    assert values[0] == 0.5
    assert values[1] is None
    assert values[13] == 0.0
    assert sum(v for v in values if v is not None) == 0.5


def test_bucketize_sums_hours_into_days():
    w = window("day", date(2026, 10, 6), MNL, NOW)
    hourly = {
        int(local(2026, 10, 6, 1).timestamp()): 0.25,
        int(local(2026, 10, 6, 23).timestamp()): 0.5,
        int(local(2026, 10, 7, 0).timestamp()): 1.0,
    }
    values = bucketize(hourly, w)
    assert values[0] is None
    assert values[5] == 0.75
    assert values[6] == 1.0

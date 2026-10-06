"""Consumption rule and time bucketing. Pure functions, no IO."""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

PERIODS = ("hour", "day", "week", "month", "year")
WEEKS_PER_WINDOW = 12


def consumption_delta(last_value: float | None, value: float, status: str) -> float:
    """Consumption added by an accepted reading.

    A `reset` reading or the first reading of a device is a new baseline. Negative deltas are
    dropped so a misread or meter swap never shows as negative consumption.
    """
    if status == "reset" or last_value is None:
        return 0.0
    delta = value - last_value
    return delta if delta > 0 else 0.0


def hour_floor(ts: int) -> int:
    return ts - ts % 3600


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    buckets: list[datetime]  # bucket i spans [buckets[i], buckets[i + 1]), the last ends at `end`
    prev_anchor: date | None
    next_anchor: date | None


def _midnight(d: date, tz: ZoneInfo) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def _first_of_month(d: date, months_later: int) -> date:
    m = d.month - 1 + months_later
    return date(d.year + m // 12, m % 12 + 1, 1)


def window(period: str, anchor: date, tz: ZoneInfo, now: datetime,
           first_year: int | None = None) -> Window:
    if period == "hour":
        start_d, end_d = anchor, anchor + timedelta(days=1)
        days = []
    elif period == "day":
        start_d = anchor.replace(day=1)
        end_d = _first_of_month(start_d, 1)
        days = [start_d + timedelta(days=i) for i in range((end_d - start_d).days)]
    elif period == "week":
        end_d = anchor - timedelta(days=anchor.weekday()) + timedelta(weeks=1)
        start_d = end_d - timedelta(weeks=WEEKS_PER_WINDOW)
        days = [start_d + timedelta(weeks=i) for i in range(WEEKS_PER_WINDOW)]
    elif period == "month":
        start_d, end_d = date(anchor.year, 1, 1), date(anchor.year + 1, 1, 1)
        days = [_first_of_month(start_d, i) for i in range(12)]
    elif period == "year":
        first = min(first_year or now.year, now.year)
        start_d, end_d = date(first, 1, 1), date(now.year + 1, 1, 1)
        days = [date(y, 1, 1) for y in range(first, now.year + 1)]
    else:
        raise ValueError(f"unknown period {period!r}")

    start, end = _midnight(start_d, tz), _midnight(end_d, tz)
    if period == "hour":
        # Step in UTC so DST days get 23 or 25 buckets.
        buckets = [datetime.fromtimestamp(t, tz)
                   for t in range(int(start.timestamp()), int(end.timestamp()), 3600)]
    else:
        buckets = [_midnight(d, tz) for d in days]

    if period == "year":
        prev_anchor = next_anchor = None
    else:
        prev_anchor = start_d - timedelta(days=1)
        if period == "week":
            next_anchor = end_d + timedelta(weeks=WEEKS_PER_WINDOW - 1)
        else:
            next_anchor = end_d
        if end > now:
            next_anchor = None
    return Window(start, end, buckets, prev_anchor, next_anchor)


def bucketize(hourly: dict[int, float], win: Window) -> list[float | None]:
    """Sum hourly rollup rows (UTC hour start -> kWh) into the window's buckets.

    A bucket with no rows is None (no data); a bucket whose rows sum to 0 is 0.0.
    """
    edges = [int(b.timestamp()) for b in win.buckets]
    end = int(win.end.timestamp())
    out: list[float | None] = [None] * len(edges)
    for ts, value in hourly.items():
        if ts < edges[0] or ts >= end:
            continue
        i = bisect_right(edges, ts) - 1
        out[i] = (out[i] or 0.0) + value
    return out

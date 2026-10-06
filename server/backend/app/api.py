"""JSON API."""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from . import db
from .consumption import bucketize, window

router = APIRouter()
UNIT = "kWh"
Period = Literal["hour", "day", "week", "month", "year"]


def get_conn(request: Request):
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _iso(ts: int | None, tz) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz).isoformat(timespec="seconds")


def _date(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


@router.get("/devices")
def list_devices(request: Request, conn=Depends(get_conn)):
    tz = request.app.state.settings.tz
    return [{
        "id": r["id"],
        "name": r["name"],
        "online": None if r["online"] is None else bool(r["online"]),
        "ip": r["ip"],
        "last_seen": _iso(r["last_seen"], tz),
        "last_value": r["last_value"],
        "last_value_ts": _iso(r["last_value_ts"], tz),
    } for r in db.list_devices(conn)]


@router.get("/devices/{device_id}/consumption")
def device_consumption(device_id: str, request: Request, period: Period = "hour",
                       anchor: date | None = None, conn=Depends(get_conn)):
    device = db.get_device(conn, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="unknown device")
    tz = request.app.state.settings.tz
    now = request.app.state.clock()

    first = db.first_hour(conn, device_id)
    first_year = datetime.fromtimestamp(first, tz).year if first is not None else None
    win = window(period, anchor or now.date(), tz, now, first_year)
    start, end = int(win.start.timestamp()), int(win.end.timestamp())

    values = bucketize(db.hourly_between(conn, device_id, start, end), win)
    first_r, last_r = db.accepted_bounds(conn, device_id, start, end)
    differential = None
    if first_r is not None:
        differential = {
            "start_value": first_r["value"], "start_ts": _iso(first_r["ts"], tz),
            "end_value": last_r["value"], "end_ts": _iso(last_r["ts"], tz),
        }
    current = None
    if device["last_value"] is not None:
        current = {"value": device["last_value"], "ts": _iso(device["last_value_ts"], tz)}

    return {
        "period": period,
        "unit": UNIT,
        "window_start": win.start.isoformat(timespec="seconds"),
        "window_end": win.end.isoformat(timespec="seconds"),
        "prev_anchor": _date(win.prev_anchor),
        "next_anchor": _date(win.next_anchor),
        "buckets": [
            {"start": b.isoformat(timespec="seconds"),
             "consumption": None if v is None else round(v, 6)}
            for b, v in zip(win.buckets, values)
        ],
        "total": round(sum(v for v in values if v is not None), 6),
        "differential": differential,
        "has_reset": db.has_reset(conn, device_id, start, end),
        "current": current,
    }

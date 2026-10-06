"""SQLite schema, writes, and read queries."""
import sqlite3

from .consumption import consumption_delta, hour_floor

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT,
    online INTEGER,
    ip TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    last_value REAL,
    last_value_ts INTEGER
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    device_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    status TEXT NOT NULL,
    value REAL,
    raw TEXT,
    min_conf REAL
);
CREATE INDEX IF NOT EXISTS readings_device_ts ON readings (device_id, ts);
CREATE TABLE IF NOT EXISTS hourly (
    device_id TEXT NOT NULL,
    hour_ts INTEGER NOT NULL,
    consumption REAL NOT NULL,
    PRIMARY KEY (device_id, hour_ts)
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _touch_device(conn, device_id: str, ts: int) -> None:
    conn.execute(
        "INSERT INTO devices (id, first_seen, last_seen) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen",
        (device_id, ts, ts))


def upsert_status(conn, device_id: str, online: bool, ip: str | None, ts: int) -> None:
    with conn:
        _touch_device(conn, device_id, ts)
        conn.execute("UPDATE devices SET online = ?, ip = COALESCE(?, ip) WHERE id = ?",
                     (int(online), ip, device_id))


def _apply_accepted(conn, device_id: str, ts: int, status: str, value: float) -> None:
    row = conn.execute("SELECT last_value FROM devices WHERE id = ?", (device_id,)).fetchone()
    delta = consumption_delta(row["last_value"], value, status)
    # The row is created even for a zero delta so the API can tell "no consumption" from "no data".
    conn.execute(
        "INSERT INTO hourly (device_id, hour_ts, consumption) VALUES (?, ?, ?) "
        "ON CONFLICT(device_id, hour_ts) DO UPDATE SET consumption = consumption + excluded.consumption",
        (device_id, hour_floor(ts), delta))
    conn.execute("UPDATE devices SET last_value = ?, last_value_ts = ? WHERE id = ?",
                 (value, ts, device_id))


def record_reading(conn, device_id: str, ts: int, ok: bool, status: str, value: float | None,
                   raw: str, min_conf: float | None) -> None:
    with conn:
        _touch_device(conn, device_id, ts)
        conn.execute(
            "INSERT INTO readings (device_id, ts, ok, status, value, raw, min_conf) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (device_id, ts, int(ok), status, value, raw, min_conf))
        if ok:
            _apply_accepted(conn, device_id, ts, status, value)


def rebuild_rollup(conn) -> None:
    """Recompute `hourly` and each device's last value from `readings`."""
    with conn:
        conn.execute("DELETE FROM hourly")
        conn.execute("UPDATE devices SET last_value = NULL, last_value_ts = NULL")
        rows = conn.execute(
            "SELECT device_id, ts, status, value FROM readings WHERE ok = 1 ORDER BY ts, id"
        ).fetchall()
        for r in rows:
            _apply_accepted(conn, r["device_id"], r["ts"], r["status"], r["value"])


def list_devices(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM devices ORDER BY (online IS NOT 1), id").fetchall()


def get_device(conn, device_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()


def hourly_between(conn, device_id: str, start_ts: int, end_ts: int) -> dict[int, float]:
    rows = conn.execute(
        "SELECT hour_ts, consumption FROM hourly "
        "WHERE device_id = ? AND hour_ts >= ? AND hour_ts < ?",
        (device_id, start_ts, end_ts))
    return {r["hour_ts"]: r["consumption"] for r in rows}


def first_hour(conn, device_id: str) -> int | None:
    return conn.execute("SELECT MIN(hour_ts) FROM hourly WHERE device_id = ?",
                        (device_id,)).fetchone()[0]


def accepted_bounds(conn, device_id: str, start_ts: int,
                    end_ts: int) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
    query = ("SELECT ts, value FROM readings "
             "WHERE device_id = ? AND ok = 1 AND ts >= ? AND ts < ? "
             "ORDER BY ts {0}, id {0} LIMIT 1")
    args = (device_id, start_ts, end_ts)
    first = conn.execute(query.format("ASC"), args).fetchone()
    last = conn.execute(query.format("DESC"), args).fetchone()
    return first, last


def has_reset(conn, device_id: str, start_ts: int, end_ts: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM readings WHERE device_id = ? AND ok = 1 AND status = 'reset' "
        "AND ts >= ? AND ts < ? LIMIT 1",
        (device_id, start_ts, end_ts)).fetchone()
    return row is not None

import json

import pytest

from app import db
from app.ingest import handle_message

T0 = 1_800_000_000  # an exact hour start (500000 * 3600)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    yield c
    c.close()


def reading(value=None, status="ok", ok=True):
    d = {"ok": ok, "status": status, "raw": "0001234", "min_conf": 0.97, "dx": 0, "dy": 0,
         "uptime_s": 5}
    if value is not None:
        d["value"] = value
    return json.dumps(d).encode()


def device(conn, device_id):
    return conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()


def hourly(conn):
    return {(r["device_id"], r["hour_ts"]): r["consumption"]
            for r in conn.execute("SELECT * FROM hourly")}


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_status_creates_online_device(conn):
    handle_message(conn, "meter", "meter/m1/status", b'{"online":true,"ip":"10.0.0.5"}', T0)
    d = device(conn, "m1")
    assert d["online"] == 1
    assert d["ip"] == "10.0.0.5"
    assert d["first_seen"] == T0
    assert d["last_seen"] == T0


def test_lwt_marks_offline_and_keeps_ip(conn):
    handle_message(conn, "meter", "meter/m1/status", b'{"online":true,"ip":"10.0.0.5"}', T0)
    handle_message(conn, "meter", "meter/m1/status", b'{"online":false}', T0 + 60)
    d = device(conn, "m1")
    assert d["online"] == 0
    assert d["ip"] == "10.0.0.5"
    assert d["first_seen"] == T0
    assert d["last_seen"] == T0 + 60


def test_first_reading_is_baseline_for_unknown_device(conn):
    handle_message(conn, "meter", "meter/m1/reading", reading(100.0), T0)
    d = device(conn, "m1")
    assert d["online"] is None
    assert d["last_value"] == 100.0
    assert d["last_value_ts"] == T0
    assert hourly(conn) == {("m1", T0): 0.0}


def test_deltas_go_into_the_hour_of_the_later_reading(conn):
    handle_message(conn, "meter", "meter/m1/reading", reading(100.0), T0 + 10)
    handle_message(conn, "meter", "meter/m1/reading", reading(100.5), T0 + 600)
    handle_message(conn, "meter", "meter/m1/reading", reading(101.25), T0 + 3605)
    assert hourly(conn) == {("m1", T0): 0.5, ("m1", T0 + 3600): 0.75}
    d = device(conn, "m1")
    assert d["last_value"] == 101.25
    assert d["last_value_ts"] == T0 + 3605


def test_reset_starts_new_baseline(conn):
    handle_message(conn, "meter", "meter/m1/reading", reading(100.0), T0)
    handle_message(conn, "meter", "meter/m1/reading", reading(5.0, status="reset"), T0 + 60)
    handle_message(conn, "meter", "meter/m1/reading", reading(6.0), T0 + 120)
    assert hourly(conn) == {("m1", T0): 1.0}
    assert count(conn, "readings") == 3


def test_rejected_reading_is_stored_but_not_counted(conn):
    handle_message(conn, "meter", "meter/m1/reading", reading(100.0), T0)
    handle_message(conn, "meter", "meter/m1/reading",
                   reading(status="low_confidence", ok=False), T0 + 3600)
    rows = conn.execute("SELECT ok, status, value, min_conf FROM readings ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "ok", 100.0, 0.97), (0, "low_confidence", None, 0.97)]
    assert hourly(conn) == {("m1", T0): 0.0}
    assert device(conn, "m1")["last_value"] == 100.0


@pytest.mark.parametrize("topic,payload", [
    ("meter/m1/reading", b"not json"),
    ("meter/m1/reading", b"\xff\xfe"),
    ("meter/m1/reading", b"[1, 2]"),
    ("meter/m1/reading", b'{"ok":true,"status":"ok"}'),
    ("meter/m1/reading", b'{"ok":true,"status":"ok","value":"12"}'),
    ("meter/m1/reading", b'{"ok":true,"status":"ok","value":true}'),
    ("meter/m1/reading", b'{"ok":true,"value":1}'),
    ("meter/m1/status", b'{"online":"yes"}'),
    ("meter/m1/status", b'{}'),
])
def test_malformed_messages_are_dropped(conn, topic, payload):
    handle_message(conn, "meter", topic, payload, T0)
    assert count(conn, "devices") == 0
    assert count(conn, "readings") == 0


@pytest.mark.parametrize("topic", [
    "meter/m1/extra/reading",
    "other/m1/reading",
    "meter/m1/config",
    "meter//reading",
    "meterx/m1/reading",
])
def test_foreign_topics_are_ignored(conn, topic):
    handle_message(conn, "meter", topic, reading(1.0), T0)
    assert count(conn, "devices") == 0


def test_prefix_with_slash(conn):
    handle_message(conn, "site/meter", "site/meter/m1/reading", reading(1.0), T0)
    assert device(conn, "m1")["last_value"] == 1.0


def test_rebuild_rollup_matches_live_ingest(conn):
    feed = [
        (reading(100.0), T0 + 10),
        (reading(100.5), T0 + 600),
        (reading(status="invalid", ok=False), T0 + 900),
        (reading(5.0, status="reset"), T0 + 3600),
        (reading(7.5), T0 + 7300),
    ]
    for payload, ts in feed:
        handle_message(conn, "meter", "meter/m1/reading", payload, ts)
    live_hourly = hourly(conn)
    live_device = tuple(device(conn, "m1"))

    with conn:
        conn.execute("UPDATE hourly SET consumption = 99")
    db.rebuild_rollup(conn)

    assert hourly(conn) == live_hourly
    assert tuple(device(conn, "m1")) == live_device

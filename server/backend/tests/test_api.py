import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import db
from app.ingest import handle_message
from app.main import create_app
from app.settings import Settings

MNL = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=MNL)


def ts(h, m=0, day=6):
    return int(datetime(2026, 10, day, h, m, tzinfo=MNL).timestamp())


def reading(value, status="ok"):
    return json.dumps({"ok": True, "status": status, "raw": "x", "value": value,
                       "min_conf": 0.9}).encode()


@pytest.fixture
def client(tmp_path):
    path = str(tmp_path / "test.db")
    conn = db.connect(path)

    def feed(topic, payload, t):
        handle_message(conn, "meter", topic, payload, t)

    feed("meter/meter-b/status", b'{"online":true,"ip":"10.0.0.7"}', ts(7))
    feed("meter/meter-a/status", b'{"online":false}', ts(7))
    feed("meter/meter-b/reading", reading(100.0), ts(8, 10))
    feed("meter/meter-b/reading", reading(100.5), ts(8, 40))
    feed("meter/meter-b/reading", reading(101.25), ts(9, 5))
    feed("meter/meter-b/reading", reading(5.0, status="reset"), ts(11, 0))
    feed("meter/meter-b/reading", reading(6.0), ts(11, 30))
    feed("meter/meter-c/reading", b'{"ok":false,"status":"capture_failed","raw":""}', ts(9))
    conn.close()

    settings = Settings(mqtt_url="mqtt://unused", mqtt_prefix="meter", db_path=path, tz=MNL,
                        static_dir=None)
    app = create_app(settings, start_mqtt=False, clock=lambda: NOW)
    with TestClient(app) as c:
        yield c


def test_devices_sorted_online_first(client):
    body = client.get("/api/devices").json()
    assert [d["id"] for d in body] == ["meter-b", "meter-a", "meter-c"]
    b, a, c = body
    assert b == {"id": "meter-b", "name": None, "online": True, "ip": "10.0.0.7",
                 "last_seen": "2026-10-06T11:30:00+08:00", "last_value": 6.0,
                 "last_value_ts": "2026-10-06T11:30:00+08:00"}
    assert a["online"] is False
    assert a["last_value"] is None
    assert a["last_value_ts"] is None
    assert c["online"] is None


def test_hourly_consumption(client):
    body = client.get("/api/devices/meter-b/consumption",
                      params={"period": "hour", "anchor": "2026-10-06"}).json()
    assert body["period"] == "hour"
    assert body["unit"] == "kWh"
    assert body["window_start"] == "2026-10-06T00:00:00+08:00"
    assert body["window_end"] == "2026-10-07T00:00:00+08:00"
    assert body["prev_anchor"] == "2026-10-05"
    assert body["next_anchor"] is None
    buckets = body["buckets"]
    assert len(buckets) == 24
    assert buckets[0] == {"start": "2026-10-06T00:00:00+08:00", "consumption": None}
    assert buckets[8] == {"start": "2026-10-06T08:00:00+08:00", "consumption": 0.5}
    assert buckets[9]["consumption"] == 0.75
    assert buckets[10]["consumption"] is None
    assert buckets[11]["consumption"] == 1.0
    assert body["total"] == 2.25
    assert body["differential"] == {
        "start_value": 100.0, "start_ts": "2026-10-06T08:10:00+08:00",
        "end_value": 6.0, "end_ts": "2026-10-06T11:30:00+08:00"}
    assert body["has_reset"] is True
    assert body["current"] == {"value": 6.0, "ts": "2026-10-06T11:30:00+08:00"}


def test_anchor_defaults_to_today(client):
    implicit = client.get("/api/devices/meter-b/consumption", params={"period": "hour"}).json()
    explicit = client.get("/api/devices/meter-b/consumption",
                          params={"period": "hour", "anchor": "2026-10-06"}).json()
    assert implicit == explicit


def test_period_defaults_to_hour(client):
    body = client.get("/api/devices/meter-b/consumption").json()
    assert body["period"] == "hour"


def test_daily_consumption(client):
    body = client.get("/api/devices/meter-b/consumption",
                      params={"period": "day", "anchor": "2026-10-06"}).json()
    assert len(body["buckets"]) == 31
    assert body["buckets"][5] == {"start": "2026-10-06T00:00:00+08:00", "consumption": 2.25}
    assert body["buckets"][4]["consumption"] is None
    assert body["total"] == 2.25


def test_yearly_consumption(client):
    body = client.get("/api/devices/meter-b/consumption", params={"period": "year"}).json()
    assert body["buckets"] == [{"start": "2026-01-01T00:00:00+08:00", "consumption": 2.25}]
    assert body["prev_anchor"] is None
    assert body["next_anchor"] is None


def test_window_without_data(client):
    body = client.get("/api/devices/meter-b/consumption",
                      params={"period": "hour", "anchor": "2026-10-05"}).json()
    assert all(b["consumption"] is None for b in body["buckets"])
    assert body["total"] == 0
    assert body["differential"] is None
    assert body["has_reset"] is False
    assert body["next_anchor"] == "2026-10-06"
    assert body["current"] == {"value": 6.0, "ts": "2026-10-06T11:30:00+08:00"}


def test_status_only_device_has_empty_consumption(client):
    body = client.get("/api/devices/meter-a/consumption", params={"period": "hour"}).json()
    assert all(b["consumption"] is None for b in body["buckets"])
    assert body["total"] == 0
    assert body["differential"] is None
    assert body["current"] is None
    year = client.get("/api/devices/meter-a/consumption", params={"period": "year"}).json()
    assert year["buckets"] == [{"start": "2026-01-01T00:00:00+08:00", "consumption": None}]


def test_future_anchor_is_empty_and_has_no_next(client):
    body = client.get("/api/devices/meter-b/consumption",
                      params={"period": "hour", "anchor": "2030-01-01"}).json()
    assert all(b["consumption"] is None for b in body["buckets"])
    assert body["next_anchor"] is None
    assert body["prev_anchor"] == "2029-12-31"


def test_unknown_device_is_404(client):
    assert client.get("/api/devices/nope/consumption").status_code == 404


@pytest.mark.parametrize("params", [{"period": "minute"}, {"anchor": "2026-13-01"}])
def test_bad_query_is_422(client, params):
    assert client.get("/api/devices/meter-b/consumption", params=params).status_code == 422

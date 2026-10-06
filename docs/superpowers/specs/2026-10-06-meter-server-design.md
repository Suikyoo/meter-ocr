# Meter server and mobile web app: design

Date: 2026-10-06
Status: approved in conversation, pending written-spec review

## Goal

Replace Node-RED as the way to view meter readings with a web app that works well on a phone.
The app lists every meter device it has heard from, and for one device shows consumption over a
selectable period as a bar chart plus text.

Success criteria:

- New devices appear in the list without any server-side configuration.
- The list shows whether each device is online, offline, or of unknown state.
- The device page shows, for a chosen partition (hourly, daily, weekly, monthly, yearly) and
  window, a bar per bucket, the window total, the start and end meter values, and the current
  meter value.
- A meter swap (firmware status `reset`) never shows up as negative or huge consumption.
- The whole stack runs with `docker compose up -d` on a LAN machine.

Out of scope for this version: authentication, TLS, renaming devices in the UI, alerts, CSV export,
units other than kWh.

## Part 1: firmware MQTT contract

The current firmware publishes every device to one fixed topic (`meter/reading`), has no device ID
in the payload, and sets no LWT or status message. The server cannot tell devices apart or know
whether they are online. This part fixes that.

### Device ID

`meter-` followed by the 12 lowercase hex characters of the WiFi STA MAC address, for example
`meter-a1b2c3d4e5f6`. It is also used as the MQTT `client_id`. It needs no configuration and stays
the same across reflashes.

### Topics

| Topic | Retained | QoS | Payload |
|---|---|---|---|
| `<prefix>/<id>/status` | yes | 1 | `{"online":true,"ip":"192.168.1.42"}`, published on every connect |
| `<prefix>/<id>/status` (LWT) | yes | 1 | `{"online":false}` |
| `<prefix>/<id>/reading` | no | 1 | Existing reading JSON, unchanged |

`<prefix>` defaults to `meter`.

The reading JSON stays as `reading_to_json(r, false)` produces it today: `ok`, `status`, `raw`,
`value` (present only when `ok` is true), `min_conf`, `dx`, `dy`, `uptime_s`. `ok` is true for
status `ok` and status `reset`, and false for every other status.

### Firmware changes

- `firmware/main/Kconfig.projbuild`: replace `METER_MQTT_TOPIC` with `METER_MQTT_PREFIX`
  (default `meter`).
- `firmware/main/net.cc`:
  - Build the device ID from `esp_read_mac(..., ESP_MAC_WIFI_STA)`.
  - Set `credentials.client_id` to the device ID.
  - Set `session.last_will` to topic `<prefix>/<id>/status`, payload `{"online":false}`,
    QoS 1, retained.
  - Set `session.keepalive` to 30 s so the broker publishes the LWT within about 45 s of the
    device dying.
  - Register an `MQTT_EVENT_CONNECTED` handler that publishes the retained online status,
    including the station IP. This also covers reconnects.
  - Publish readings to `<prefix>/<id>/reading`.
- `README.md`: document the topics and payloads.

The device still has no wall-clock time. The server timestamps readings on arrival. Readings
published while the broker is unreachable are lost; this is accepted for now.

## Part 2: server

### Layout

```
server/
  backend/                Python 3.12, managed with uv
    app/main.py             FastAPI app; lifespan starts and stops the MQTT client
    app/ingest.py           MQTT subscription and message handling
    app/db.py               SQLite schema and queries
    app/consumption.py      pure delta and bucket logic, no IO
    app/api.py              JSON endpoints
    app/cli.py              rebuild-rollup command
    scripts/fake_meter.py   simulated devices for development
    tests/
  frontend/               Svelte 5 + Vite SPA
  Dockerfile              stage 1 builds the frontend, stage 2 runs Python with the built files
  docker-compose.yml      mosquitto + app
  mosquitto.conf          anonymous access on the LAN, persistence on
```

### Configuration

Environment variables, with defaults set in `docker-compose.yml`:

| Variable | Default |
|---|---|
| `MQTT_URL` | `mqtt://mosquitto:1883` |
| `MQTT_PREFIX` | `meter` |
| `DB_PATH` | `/data/meter.db` |
| `TZ` | `Asia/Manila` |

The app listens on port 8080. Mosquitto listens on port 1883.

### Device discovery

The server subscribes to `<prefix>/+/status` and `<prefix>/+/reading`. Because status messages are
retained, the broker sends the status of every known device as soon as the server connects. A
device that sends readings but has never sent a status message is still listed, with `online`
set to `null` (unknown).

### SQLite schema

SQLite runs in WAL mode. The ingest thread is the only writer. API requests use their own
read connections.

`devices`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PRIMARY KEY | device ID from the topic |
| `name` | TEXT NULL | reserved for renaming, unused in this version |
| `online` | INTEGER NULL | 1, 0, or NULL if no status received |
| `ip` | TEXT NULL | from the last status message |
| `first_seen` | INTEGER | UTC seconds |
| `last_seen` | INTEGER | UTC seconds, any message |
| `last_value` | REAL NULL | last accepted meter value |
| `last_value_ts` | INTEGER NULL | UTC seconds |

`readings`: one row per reading message, accepted or not.

| Column | Type |
|---|---|
| `id` | INTEGER PRIMARY KEY |
| `device_id` | TEXT |
| `ts` | INTEGER (UTC seconds, server arrival time) |
| `ok` | INTEGER |
| `status` | TEXT |
| `value` | REAL NULL |
| `raw` | TEXT |
| `min_conf` | REAL |

Index on `(device_id, ts)`.

`hourly`: consumption rollup, primary key `(device_id, hour_ts)`, column `consumption REAL`.
`hour_ts` is the UTC timestamp of the start of the hour.

### Ingest rule

For each message on `<prefix>/<id>/reading`:

1. Upsert the device and set `last_seen`.
2. Insert the reading into `readings`.
3. If `ok` is false, stop.
4. Make sure the `hourly` row for the reading's hour exists (insert with consumption 0 if not).
   This lets the API tell "data but no consumption" (0) from "no data" (gap).
5. If status is `reset`, or the device has no `last_value`, the reading becomes the new baseline
   and adds no consumption.
6. Otherwise, compute `delta = value - last_value`. If `delta > 0`, add it to the `hourly` row.
   Negative deltas are dropped.
7. Set `last_value` and `last_value_ts` to this reading.

For each message on `<prefix>/<id>/status`: upsert the device and set `online`, `ip` (if present),
and `last_seen`.

Error handling:

- Malformed JSON, a missing `status`, or a non-numeric `value` on an `ok` reading: log the topic
  and reason, drop the message.
- Topics that do not match `<prefix>/<id>/(status|reading)`: ignore.
- MQTT disconnect: paho reconnects with backoff. Log each disconnect and reconnect. The API keeps
  serving stored data.

The delta and baseline decision (steps 5 and 6) lives in `consumption.py` as a pure function so it
can be unit tested and reused by the rebuild command.

Known limitation: after a device has been offline for several hours, the whole jump lands in the
hour of the first reading after it returns. It is not spread over the gap.

### Rollup rebuild

`python -m app.cli rebuild-rollup` deletes `hourly` and recomputes it, and each device's
`last_value`, from `readings` in timestamp order, using the same rule. Use it after changing the
rule.

### Bucketing

All partitions are sums of `hourly` rows, grouped into local-time buckets in Python with
`zoneinfo` and the `TZ` setting. This handles DST (23 h and 25 h days). Weeks start on Monday.

Rollup hours are UTC hours. In a zone with a whole-hour offset (such as `Asia/Manila`, UTC+8)
local hours line up exactly. In a zone with a non-whole-hour offset, an hourly bucket can be off by
the fraction; this is accepted.

A bucket with no `hourly` rows is a gap (`null`). A bucket with rows whose sum is 0 is `0`.

## Part 3: HTTP API

All timestamps in responses are ISO 8601 in the server's local zone.

### `GET /api/devices`

```json
[{"id":"meter-a1b2c3d4e5f6","name":null,"online":true,"ip":"192.168.1.42",
  "last_seen":"2026-10-06T10:58:12+08:00","last_value":12456.8,
  "last_value_ts":"2026-10-06T10:58:12+08:00"}]
```

Sorted with online devices first, then by `id`.

### `GET /api/devices/{id}/consumption?period=<p>&anchor=<YYYY-MM-DD>`

`period` is one of `hour`, `day`, `week`, `month`, `year`. `anchor` defaults to today.

| period | Window | Bars |
|---|---|---|
| `hour` | the local day containing `anchor` | 24 (23 or 25 on DST days) |
| `day` | the month containing `anchor` | 28 to 31 |
| `week` | 12 weeks ending with the week containing `anchor`, Monday start | 12 |
| `month` | the year containing `anchor` | 12 |
| `year` | first year with data through the current year | one per year |

Response:

```json
{"period":"hour","unit":"kWh",
 "window_start":"2026-10-06T00:00:00+08:00","window_end":"2026-10-07T00:00:00+08:00",
 "prev_anchor":"2026-10-05","next_anchor":null,
 "buckets":[{"start":"2026-10-06T00:00:00+08:00","consumption":0.42},
            {"start":"2026-10-06T01:00:00+08:00","consumption":null}],
 "total":8.91,
 "differential":{"start_value":12447.9,"start_ts":"2026-10-06T00:00:41+08:00",
                 "end_value":12456.8,"end_ts":"2026-10-06T10:58:12+08:00"},
 "has_reset":false,
 "current":{"value":12456.8,"ts":"2026-10-06T10:58:12+08:00"}}
```

- `total` is the sum of non-null buckets.
- `differential` is the first and last accepted readings inside the window, or `null` if there
  are none.
- `has_reset` is true when a `reset` reading falls inside the window. `differential` then differs
  from `total`, and `total` is the trusted number.
- `prev_anchor` and `next_anchor` step one window back or forward. `next_anchor` is `null` when
  the next window would start after now. For `year`, both are `null`.
- `current` is the device's `last_value` and `last_value_ts`, or `null`.
- Unknown device: `404`. Invalid `period` or `anchor`: `422`.

### Static files

FastAPI serves the built SPA from `/`. API routes live under `/api`.

## Part 4: frontend

Svelte 5 + Vite single-page app, mobile first. Hash routing without a router library:

- `#/`: device list
- `#/device/<id>`: device page

Both screens poll their endpoint every 30 s while `document.visibilityState` is `visible`, and
refetch when the page becomes visible again.

### Device list

```
┌──────────────────────────────┐
│ Meters                       │
├──────────────────────────────┤
│ ● meter-a1b2c3d4e5f6      ›  │
│   12,456.8 kWh · 1 min ago   │
├──────────────────────────────┤
│ ○ meter-0f9e8d7c6b5a      ›  │
│   8,102.3 kWh · offline 3 h  │
└──────────────────────────────┘
```

- ● online, ○ offline, ◌ unknown. State is also given as text, not by color alone.
- Each row is one tap target, at least 48 px tall.
- Empty state: "No meters yet. Devices appear here once they connect to the MQTT broker."

### Device page

```
┌──────────────────────────────┐
│ ‹ meter-a1b2c3d4e5f6  ● online│
│   Setup page ↗               │
│ [Hourly|Daily|Weekly|Monthly|Yearly]
│   ‹   Mon, Oct 6 2026   ›    │
│                              │
│   8.91 kWh                   │
│   used this day              │
│   12,447.9 → 12,456.8 kWh    │
│                              │
│  ▂▁▁▁▁▂▄▆▅▃▃▄▅▄▃▃▄▆█▇▅▃▂▁    │
│  0   6   12   18             │
│                              │
│ Meter now: 12,456.8 kWh · 10:58
└──────────────────────────────┘
```

- Partition control: segmented control, scrolls sideways on narrow screens. Changing the
  partition keeps the anchor date.
- Window label per partition: "Mon, Oct 6 2026", "October 2026", "Aug 18 – Nov 9 2026", "2026",
  "All years".
- The ‹ › arrows use `prev_anchor` and `next_anchor`. An arrow is disabled when its anchor is
  `null`.
- Big number: `total` with unit. Below it, the differential as start → end values.
- When `has_reset` is true, show: "Meter reset in this period. Total excludes the jump."
- Bar chart with Chart.js. Tapping a bar shows its time range and kWh. Null buckets are blank,
  not drawn as zero.
- "Setup page ↗" only when `ip` is known; opens `http://<ip>/` in a new tab.
- Loading: skeleton blocks. Fetch error: a "Couldn't load. Retry" banner, and the last data stays
  on screen.
- System font, light and dark from `prefers-color-scheme`, one accent color, no UI kit.

## Part 5: deployment

`cd server && docker compose up -d` starts:

- `mosquitto` on port 1883, with volume `mosquitto-data` so retained status messages survive a
  restart.
- `app` on port 8080, with volume `app-data` for SQLite.

Firmware `menuconfig` then points `METER_MQTT_URI` at `mqtt://<lan-box-ip>:1883`.

`scripts/fake_meter.py` publishes as N simulated devices: a retained online status, an LWT, and a
rising reading every few seconds, with optional `reset` readings and random dropouts. It lets the
whole stack be checked before any ESP32 is flashed.

## Part 6: testing

- `consumption.py`, pytest unit tests:
  - delta rule: normal delta, first reading as baseline, `reset` as baseline, negative delta
    dropped, rejected reading ignored;
  - bucketing for every partition, Monday week start, month lengths, leap year, and DST days in
    `Europe/Berlin`;
  - window bounds and `prev_anchor`/`next_anchor`, including the "next window is in the future"
    case.
- Ingest: feed fake MQTT messages to the handler with an in-memory SQLite database; assert on
  `devices`, `readings`, and `hourly` rows. Includes malformed payloads and foreign topics.
- Rollup rebuild: rebuilding from `readings` gives the same `hourly` rows as live ingest.
- API: FastAPI `TestClient` on a seeded database; response shape, gaps vs zero, `has_reset`,
  `404`, `422`.
- Frontend: Vitest for number and date formatting and window labels. Layout is checked by hand at
  phone width.
- End to end: `docker compose up`, run `fake_meter.py`, check both screens in a browser at phone
  width, stop a fake device and see it go offline.
- Firmware: ESP-IDF is not installed on the development machine, so the firmware change cannot be
  built there. It must be built and flashed by the user, or ESP-IDF installed first.

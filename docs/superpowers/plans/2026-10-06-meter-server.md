# Meter Server and Mobile Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each ESP32 meter a per-device MQTT identity with online/offline status, and build a
Docker-deployed server (FastAPI + SQLite + Svelte SPA) that lists devices and charts their kWh
consumption by hour, day, week, month, or year on a phone.

**Architecture:** The firmware publishes a retained status message (with an LWT for offline) and
readings on `meter/<device-id>/...`. A Python service subscribes, stores every reading in SQLite,
and keeps an hourly consumption rollup. A JSON API groups that rollup into local-time buckets. A
Svelte 5 SPA, built in a Docker stage and served by FastAPI, shows the device list and device page.

**Tech Stack:** ESP-IDF 5.3+ (C++), Python 3.12, uv, FastAPI, uvicorn, paho-mqtt 2.x, SQLite,
pytest, Svelte 5, Vite, Chart.js, Vitest, Docker Compose, Mosquitto 2.

**Spec:** `docs/superpowers/specs/2026-10-06-meter-server-design.md`

## Global Constraints

- Device ID: `meter-` + 12 lowercase hex chars of the WiFi STA MAC, also the MQTT `client_id`.
- Topics: `<prefix>/<id>/status` (retained, QoS 1), `<prefix>/<id>/reading` (not retained, QoS 1). Prefix default `meter`.
- Status payloads: online `{"online":true,"ip":"<ip>"}`, LWT `{"online":false}`. Firmware keepalive 30 s.
- Reading JSON is unchanged from `reading_to_json(r, false)`. `ok` is true only for status `ok` and `reset`.
- Server timestamps readings on arrival (UTC seconds). All API timestamps are ISO 8601 in the server's `TZ`, `timespec="seconds"`.
- Server env: `MQTT_URL` (compose default `mqtt://mosquitto:1883`), `MQTT_PREFIX` (`meter`), `DB_PATH` (`/data/meter.db`), `TZ` (`Asia/Manila`), `STATIC_DIR`. App port 8080, Mosquitto port 1883.
- Unit is always `kWh`. Weeks start Monday. Week window is 12 weeks.
- `null` bucket = no data (gap); `0` = data but no consumption.
- Out of scope: auth, TLS, device rename UI, alerts, CSV export, other units.
- Python commands run from `server/backend` with `uv run`. Frontend commands run from `server/frontend` with `npm`.

## Review Focus

1. A device that has only sent a status message (no readings yet) is opened in the app: the page must show empty bars, total 0, no differential, no "Meter now" line, and no error. Test: `test_status_only_device_has_empty_consumption` in Task 4.
2. The user pages forward past today, or bookmarks an anchor years in the future: all buckets null, next arrow disabled, no error. Test: `test_future_anchor_is_empty_and_has_no_next` in Task 4.
3. A broker carries other traffic under the same prefix (`meter/x/y/reading`, `meter/x/config`), or the prefix itself contains `/`: foreign topics are ignored, nested prefixes work. Tests: `test_foreign_topics_are_ignored`, `test_prefix_with_slash` in Task 3.
4. A firmware bug or a hand-published message sends `"value":"12"`, `true`, or no value on an `ok` reading: the message is dropped, nothing is stored, the ingest thread keeps running. Tests: `test_malformed_messages_are_dropped` in Task 3, `test_on_message_survives_handler_error` in Task 4.
5. The server's `TZ` has DST (a deployment outside the Philippines): hourly windows on change days have 23 or 25 bars and the daily bars still sum correctly. Test: `test_hour_window_dst_days` in Task 2.

---

## File Structure

```
firmware/main/Kconfig.projbuild       METER_MQTT_TOPIC -> METER_MQTT_PREFIX
firmware/main/CMakeLists.txt          add esp_hw_support (esp_mac.h)
firmware/main/net.h / net.cc          device ID, LWT, status publish, per-device reading topic
firmware/main/main.cc                 call renamed mqtt_publish_reading()
README.md                             MQTT contract + server section
.gitignore                            server build/venv/db ignores

server/backend/pyproject.toml         deps + pytest config
server/backend/app/__init__.py        empty
server/backend/app/consumption.py     pure: delta rule, hour_floor, Window, window(), bucketize()
server/backend/app/db.py              schema, writes (status, reading, rollup rebuild), read queries
server/backend/app/ingest.py          topic/payload parsing (handle_message) + MqttIngest paho wrapper
server/backend/app/settings.py        Settings dataclass from env
server/backend/app/api.py             /api/devices, /api/devices/{id}/consumption
server/backend/app/main.py            create_app(), lifespan, static mount, module-level app
server/backend/app/cli.py             rebuild-rollup command
server/backend/scripts/fake_meter.py  simulated devices
server/backend/tests/test_consumption.py
server/backend/tests/test_ingest.py
server/backend/tests/test_api.py

server/frontend/package.json, vite.config.js, index.html
server/frontend/src/main.js, app.css, App.svelte
server/frontend/src/lib/format.js (+ format.test.js), api.js, poll.js
server/frontend/src/lib/StatusBadge.svelte, BarChart.svelte
server/frontend/src/routes/DeviceList.svelte, DevicePage.svelte

server/Dockerfile, server/.dockerignore, server/docker-compose.yml, server/mosquitto.conf
```

---

### Task 1: Firmware MQTT contract

ESP-IDF is not installed on this machine, so this task cannot be compiled here. Verification is a
code read plus a grep. The user builds and flashes it (`idf.py build flash monitor`) and checks the
log line `mqtt connected as meter-...`.

**Files:**
- Modify: `firmware/main/Kconfig.projbuild`
- Modify: `firmware/main/CMakeLists.txt`
- Modify: `firmware/main/net.h`
- Modify: `firmware/main/net.cc`
- Modify: `firmware/main/main.cc:45`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: MQTT contract from Global Constraints; `void mqtt_publish_reading(const std::string &payload);` replaces `mqtt_publish`.

- [ ] **Step 1: Replace the topic option in `firmware/main/Kconfig.projbuild`**

Replace the whole `config METER_MQTT_TOPIC` block with:

```
    config METER_MQTT_PREFIX
        string "MQTT topic prefix"
        default "meter"
        help
            Topics are <prefix>/<device-id>/status and <prefix>/<device-id>/reading.
            The device ID is "meter-" followed by the WiFi MAC address in hex.
```

- [ ] **Step 2: Add `esp_hw_support` to `firmware/main/CMakeLists.txt`**

In the `PRIV_REQUIRES` list, add `esp_hw_support` (provides `esp_mac.h`):

```
    PRIV_REQUIRES esp_http_server esp_wifi esp_netif esp_event nvs_flash mqtt json mbedtls esp_timer esp_driver_gpio esp_hw_support)
```

- [ ] **Step 3: Update `firmware/main/net.h`**

```cpp
#pragma once

#include <string>

// Connects to the WiFi network from menuconfig. Blocks until an IP is assigned.
void wifi_connect();

// Starts the MQTT client if a broker URI is configured. Uses "meter-<mac>" as the client ID,
// publishes a retained {"online":true,"ip":...} to <prefix>/<id>/status on every connect, and
// registers {"online":false} on the same topic as the last will.
void mqtt_start();

// Publishes a reading JSON to <prefix>/<id>/reading.
void mqtt_publish_reading(const std::string &payload);
```

- [ ] **Step 4: Rewrite `firmware/main/net.cc`**

```cpp
#include "net.h"

#include <cstdio>
#include <cstring>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "mqtt_client.h"

static const char *TAG = "net";
static EventGroupHandle_t s_events;
static constexpr EventBits_t kGotIp = BIT0;
static esp_mqtt_client_handle_t s_mqtt;
static char s_ip[16];
static std::string s_device_id;
static std::string s_status_topic;
static std::string s_reading_topic;
static const char kOfflineStatus[] = "{\"online\":false}";

static void on_wifi_event(void *, esp_event_base_t base, int32_t id, void *data) {
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
    esp_wifi_connect();
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    ESP_LOGW(TAG, "disconnected, retrying");
    xEventGroupClearBits(s_events, kGotIp);
    esp_wifi_connect();
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    auto *event = (ip_event_got_ip_t *)data;
    snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&event->ip_info.ip));
    ESP_LOGI(TAG, "setup page: http://%s/", s_ip);
    xEventGroupSetBits(s_events, kGotIp);
  }
}

void wifi_connect() {
  s_events = xEventGroupCreate();
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&init));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, nullptr));
  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, nullptr));

  wifi_config_t cfg = {};
  strncpy((char *)cfg.sta.ssid, CONFIG_METER_WIFI_SSID, sizeof(cfg.sta.ssid));
  strncpy((char *)cfg.sta.password, CONFIG_METER_WIFI_PASSWORD, sizeof(cfg.sta.password));
  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
  ESP_ERROR_CHECK(esp_wifi_start());

  xEventGroupWaitBits(s_events, kGotIp, pdFALSE, pdTRUE, portMAX_DELAY);
}

static void on_mqtt_event(void *, esp_event_base_t, int32_t id, void *) {
  if (id == MQTT_EVENT_CONNECTED) {
    char status[64];
    snprintf(status, sizeof(status), "{\"online\":true,\"ip\":\"%s\"}", s_ip);
    esp_mqtt_client_publish(s_mqtt, s_status_topic.c_str(), status, 0, 1, 1);
    ESP_LOGI(TAG, "mqtt connected as %s", s_device_id.c_str());
  } else if (id == MQTT_EVENT_DISCONNECTED) {
    ESP_LOGW(TAG, "mqtt disconnected");
  }
}

void mqtt_start() {
  if (strlen(CONFIG_METER_MQTT_URI) == 0) return;

  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char id[20];
  snprintf(id, sizeof(id), "meter-%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3],
           mac[4], mac[5]);
  s_device_id = id;
  std::string base = std::string(CONFIG_METER_MQTT_PREFIX) + "/" + s_device_id;
  s_status_topic = base + "/status";
  s_reading_topic = base + "/reading";

  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri = CONFIG_METER_MQTT_URI;
  cfg.credentials.client_id = s_device_id.c_str();
  cfg.session.keepalive = 30;
  cfg.session.last_will.topic = s_status_topic.c_str();
  cfg.session.last_will.msg = kOfflineStatus;
  cfg.session.last_will.msg_len = sizeof(kOfflineStatus) - 1;
  cfg.session.last_will.qos = 1;
  cfg.session.last_will.retain = 1;
  s_mqtt = esp_mqtt_client_init(&cfg);
  esp_mqtt_client_register_event(s_mqtt, (esp_mqtt_event_id_t)ESP_EVENT_ANY_ID, on_mqtt_event,
                                 nullptr);
  esp_mqtt_client_start(s_mqtt);
}

void mqtt_publish_reading(const std::string &payload) {
  if (!s_mqtt) return;
  esp_mqtt_client_publish(s_mqtt, s_reading_topic.c_str(), payload.c_str(), payload.size(), 1, 0);
}
```

- [ ] **Step 5: Update the call in `firmware/main/main.cc:45`**

```cpp
    mqtt_publish_reading(reading_to_json(r, false));
```

- [ ] **Step 6: Document the contract in `README.md`**

After the `## Install` section, add:

````markdown
## MQTT

Each device uses the ID `meter-<mac>`, where `<mac>` is its WiFi MAC address in lowercase hex.
The prefix is set in menuconfig (default `meter`).

| Topic | Retained | Payload |
|---|---|---|
| `meter/<id>/status` | yes | `{"online":true,"ip":"192.168.1.42"}`, sent on every connect |
| `meter/<id>/status` | yes | `{"online":false}`, the last will, sent by the broker about 45 s after the device drops |
| `meter/<id>/reading` | no | `{"ok":true,"status":"ok","raw":"0012345","value":1234.5,"min_conf":0.97,"dx":1,"dy":0,"uptime_s":3600}` |

`value` is present only when `ok` is true. `ok` is true for status `ok` and `reset`.
````

In the `## Firmware` section, change the menuconfig comment line to:

```sh
idf.py menuconfig        # Meter OCR: WiFi, MQTT URI/prefix, flash LED GPIO
```

- [ ] **Step 7: Verify no old references remain**

Run: `grep -rn "METER_MQTT_TOPIC\|mqtt_publish(" firmware README.md`
Expected: no output.

Run: `grep -n "METER_MQTT_PREFIX\|mqtt_publish_reading\|esp_hw_support" firmware/main/*`
Expected: hits in `Kconfig.projbuild`, `CMakeLists.txt`, `net.h`, `net.cc`, `main.cc`.

- [ ] **Step 8: Commit**

```bash
git add firmware/main/Kconfig.projbuild firmware/main/CMakeLists.txt firmware/main/net.h firmware/main/net.cc firmware/main/main.cc README.md
git commit -m "feat(firmware): per-device MQTT topics with retained status and LWT"
```

---

### Task 2: Backend project and consumption logic

**Files:**
- Create: `server/backend/pyproject.toml`
- Create: `server/backend/app/__init__.py` (empty)
- Create: `server/backend/app/consumption.py`
- Create: `server/backend/tests/test_consumption.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces (in `app.consumption`):
  - `PERIODS: tuple[str, ...] = ("hour", "day", "week", "month", "year")`
  - `WEEKS_PER_WINDOW: int = 12`
  - `consumption_delta(last_value: float | None, value: float, status: str) -> float`
  - `hour_floor(ts: int) -> int`
  - `@dataclass(frozen=True) class Window: start: datetime; end: datetime; buckets: list[datetime]; prev_anchor: date | None; next_anchor: date | None`
  - `window(period: str, anchor: date, tz: ZoneInfo, now: datetime, first_year: int | None = None) -> Window` (raises `ValueError` for unknown period)
  - `bucketize(hourly: dict[int, float], win: Window) -> list[float | None]`

- [ ] **Step 1: Create the project files**

`server/backend/pyproject.toml`:

```toml
[project]
name = "meter-server"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "paho-mqtt>=2.1",
    "tzdata>=2024.1",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`server/backend/app/__init__.py`: empty file.

Append to `.gitignore`:

```
# Server
server/backend/.venv/
server/backend/*.db*
server/frontend/node_modules/
server/frontend/dist/
```

Run: `cd server/backend && uv sync`
Expected: creates `.venv` and `uv.lock` without errors.

- [ ] **Step 2: Write the failing tests**

`server/backend/tests/test_consumption.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd server/backend && uv run pytest tests/test_consumption.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.consumption'`.

- [ ] **Step 4: Implement `server/backend/app/consumption.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd server/backend && uv run pytest tests/test_consumption.py -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add .gitignore server/backend/pyproject.toml server/backend/uv.lock server/backend/app/__init__.py server/backend/app/consumption.py server/backend/tests/test_consumption.py
git commit -m "feat(server): consumption delta rule and time-window bucketing"
```

---

### Task 3: SQLite storage and message handling

**Files:**
- Create: `server/backend/app/db.py`
- Create: `server/backend/app/ingest.py` (only `parse_topic` and `handle_message` in this task)
- Create: `server/backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `consumption_delta`, `hour_floor` from Task 2.
- Produces (in `app.db`, all take `conn: sqlite3.Connection` first; rows are `sqlite3.Row`):
  - `connect(path: str) -> sqlite3.Connection` (WAL, row factory, schema created, `check_same_thread=False`)
  - `upsert_status(conn, device_id: str, online: bool, ip: str | None, ts: int) -> None`
  - `record_reading(conn, device_id: str, ts: int, ok: bool, status: str, value: float | None, raw: str, min_conf: float | None) -> None`
  - `rebuild_rollup(conn) -> None`
  - `list_devices(conn) -> list[Row]` (online first, then id)
  - `get_device(conn, device_id) -> Row | None`
  - `hourly_between(conn, device_id, start_ts: int, end_ts: int) -> dict[int, float]`
  - `first_hour(conn, device_id) -> int | None`
  - `accepted_bounds(conn, device_id, start_ts, end_ts) -> tuple[Row | None, Row | None]` (rows have `ts`, `value`)
  - `has_reset(conn, device_id, start_ts, end_ts) -> bool`
- Produces (in `app.ingest`):
  - `parse_topic(prefix: str, topic: str) -> tuple[str, str] | None` returning `(device_id, "status" | "reading")`
  - `handle_message(conn, prefix: str, topic: str, payload: bytes, now: int) -> None`

- [ ] **Step 1: Write the failing tests**

`server/backend/tests/test_ingest.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server/backend && uv run pytest tests/test_ingest.py -q`
Expected: collection error, `ImportError` for `app.db` / `app.ingest`.

- [ ] **Step 3: Implement `server/backend/app/db.py`**

```python
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
```

- [ ] **Step 4: Implement `server/backend/app/ingest.py`**

```python
"""MQTT message parsing and storage."""
import json
import logging

from . import db

log = logging.getLogger(__name__)


def parse_topic(prefix: str, topic: str) -> tuple[str, str] | None:
    """Split `<prefix>/<device_id>/<kind>`; None for any other topic."""
    if not topic.startswith(prefix + "/"):
        return None
    parts = topic[len(prefix) + 1:].split("/")
    if len(parts) != 2 or not parts[0] or parts[1] not in ("status", "reading"):
        return None
    return parts[0], parts[1]


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def handle_message(conn, prefix: str, topic: str, payload: bytes, now: int) -> None:
    parsed = parse_topic(prefix, topic)
    if parsed is None:
        return
    device_id, kind = parsed
    try:
        data = json.loads(payload)
    except ValueError:
        log.warning("dropping %s: payload is not JSON", topic)
        return
    if not isinstance(data, dict):
        log.warning("dropping %s: payload is not an object", topic)
        return

    if kind == "status":
        online = data.get("online")
        if not isinstance(online, bool):
            log.warning("dropping %s: 'online' is not a boolean", topic)
            return
        ip = data.get("ip") if isinstance(data.get("ip"), str) else None
        db.upsert_status(conn, device_id, online, ip, now)
        return

    status = data.get("status")
    if not isinstance(status, str):
        log.warning("dropping %s: missing 'status'", topic)
        return
    ok = data.get("ok") is True
    value = data.get("value")
    if ok and not _is_number(value):
        log.warning("dropping %s: ok reading without a numeric 'value'", topic)
        return
    min_conf = data.get("min_conf")
    db.record_reading(conn, device_id, now, ok, status,
                      float(value) if ok else None,
                      str(data.get("raw", "")),
                      float(min_conf) if _is_number(min_conf) else None)
```

Note: `json.loads` raises `UnicodeDecodeError` (a `ValueError` subclass) for invalid UTF-8, so the
`except ValueError` covers the `b"\xff\xfe"` case.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd server/backend && uv run pytest -q`
Expected: all tests in `test_consumption.py` and `test_ingest.py` pass.

- [ ] **Step 6: Commit**

```bash
git add server/backend/app/db.py server/backend/app/ingest.py server/backend/tests/test_ingest.py
git commit -m "feat(server): SQLite storage, hourly rollup, and MQTT message handling"
```

---

### Task 4: API, settings, MQTT client, app wiring, and CLI

**Files:**
- Create: `server/backend/app/settings.py`
- Create: `server/backend/app/api.py`
- Create: `server/backend/app/main.py`
- Create: `server/backend/app/cli.py`
- Modify: `server/backend/app/ingest.py` (add `parse_broker_url` and `MqttIngest`)
- Create: `server/backend/tests/test_api.py`
- Modify: `server/backend/tests/test_ingest.py` (append MQTT client tests)

**Interfaces:**
- Consumes: everything from Tasks 2 and 3.
- Produces:
  - `app.settings.Settings(mqtt_url: str, mqtt_prefix: str, db_path: str, tz: ZoneInfo, static_dir: str | None)` (frozen dataclass), `load_settings() -> Settings`
  - `app.ingest.parse_broker_url(url: str) -> tuple[str, int, str | None, str | None]`
  - `app.ingest.MqttIngest(url: str, prefix: str, db_path: str)` with `start()`, `stop()`, attribute `conn`
  - `app.main.create_app(settings: Settings, start_mqtt: bool = True, clock: Callable[[], datetime] | None = None) -> FastAPI`, module-level `app`
  - HTTP: `GET /api/devices`, `GET /api/devices/{id}/consumption?period=&anchor=` with the exact JSON shapes in the spec, Part 3
  - CLI: `python -m app.cli rebuild-rollup`

- [ ] **Step 1: Write the failing API tests**

`server/backend/tests/test_api.py`:

```python
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
```

- [ ] **Step 2: Add MQTT client tests to `server/backend/tests/test_ingest.py`**

Add to the imports at the top of the file:

```python
from types import SimpleNamespace

from app import ingest
from app.ingest import MqttIngest, parse_broker_url
```

Append to the end of the file:

```python
def test_parse_broker_url():
    assert parse_broker_url("mqtt://user:p%40ss@10.0.0.2:1884") == ("10.0.0.2", 1884, "user", "p@ss")
    assert parse_broker_url("mqtt://mosquitto") == ("mosquitto", 1883, None, None)


def test_on_message_stores_reading(tmp_path):
    path = str(tmp_path / "test.db")
    ing = MqttIngest("mqtt://localhost", "meter", path)
    ing.conn = db.connect(path)
    ing._on_message(None, None, SimpleNamespace(topic="meter/m1/reading", payload=reading(1.0)))
    assert device(ing.conn, "m1")["last_value"] == 1.0
    ing.conn.close()


def test_on_message_survives_handler_error(tmp_path, monkeypatch):
    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest, "handle_message", boom)
    ing = MqttIngest("mqtt://localhost", "meter", str(tmp_path / "test.db"))
    ing._on_message(None, None, SimpleNamespace(topic="meter/m1/reading", payload=b"{}"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd server/backend && uv run pytest -q`
Expected: collection errors: `ImportError` for `app.main`, `app.settings`, and `MqttIngest`/`parse_broker_url`.

- [ ] **Step 4: Implement `server/backend/app/settings.py`**

```python
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    mqtt_url: str
    mqtt_prefix: str
    db_path: str
    tz: ZoneInfo
    static_dir: str | None


def load_settings() -> Settings:
    return Settings(
        mqtt_url=os.environ.get("MQTT_URL", "mqtt://localhost:1883"),
        mqtt_prefix=os.environ.get("MQTT_PREFIX", "meter"),
        db_path=os.environ.get("DB_PATH", "meter.db"),
        tz=ZoneInfo(os.environ.get("TZ", "Asia/Manila")),
        static_dir=os.environ.get("STATIC_DIR"),
    )
```

- [ ] **Step 5: Add the MQTT client to `server/backend/app/ingest.py`**

Add these imports at the top (next to the existing ones):

```python
import os
import time
from urllib.parse import unquote, urlparse

import paho.mqtt.client as mqtt
```

Append to the end of the file:

```python
def parse_broker_url(url: str) -> tuple[str, int, str | None, str | None]:
    u = urlparse(url)
    user = unquote(u.username) if u.username else None
    password = unquote(u.password) if u.password else None
    return u.hostname or "localhost", u.port or 1883, user, password


class MqttIngest:
    """Subscribes to device topics and stores messages. The paho network thread is the only
    SQLite writer."""

    def __init__(self, url: str, prefix: str, db_path: str):
        self.host, self.port, user, password = parse_broker_url(url)
        self.prefix = prefix
        self.db_path = db_path
        self.conn = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"meter-server-{os.getpid()}")
        if user:
            self.client.username_pw_set(user, password)
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.conn = db.connect(self.db_path)
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
        if self.conn is not None:
            self.conn.close()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("mqtt connect to %s:%s failed: %s", self.host, self.port, reason_code)
            return
        log.info("mqtt connected to %s:%s", self.host, self.port)
        client.subscribe([(f"{self.prefix}/+/status", 1), (f"{self.prefix}/+/reading", 1)])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("mqtt disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            handle_message(self.conn, self.prefix, msg.topic, msg.payload, int(time.time()))
        except Exception:
            log.exception("failed to handle message on %s", msg.topic)
```

- [ ] **Step 6: Implement `server/backend/app/api.py`**

```python
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
```

- [ ] **Step 7: Implement `server/backend/app/main.py`**

```python
"""FastAPI app: API, MQTT ingest lifecycle, and the built SPA."""
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import api, db
from .ingest import MqttIngest
from .settings import Settings, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings, start_mqtt: bool = True,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.connect(settings.db_path).close()  # create the schema before any request
        ingest = MqttIngest(settings.mqtt_url, settings.mqtt_prefix, settings.db_path) \
            if start_mqtt else None
        if ingest:
            ingest.start()
        yield
        if ingest:
            ingest.stop()

    app = FastAPI(title="Meter server", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock or (lambda: datetime.now(settings.tz))
    app.include_router(api.router, prefix="/api")
    if settings.static_dir and os.path.isdir(settings.static_dir):
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    return app


app = create_app(load_settings())
```

- [ ] **Step 8: Implement `server/backend/app/cli.py`**

```python
"""Maintenance commands. Usage: python -m app.cli rebuild-rollup"""
import argparse

from . import db
from .settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rebuild-rollup", help="recompute hourly consumption from stored readings")
    parser.parse_args(argv)

    conn = db.connect(load_settings().db_path)
    try:
        db.rebuild_rollup(conn)
    finally:
        conn.close()
    print("hourly rollup rebuilt")


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Run all backend tests**

Run: `cd server/backend && uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 10: Smoke-test the CLI**

Run: `cd server/backend && DB_PATH=smoke.db uv run python -m app.cli rebuild-rollup && rm -f smoke.db*`
Expected: prints `hourly rollup rebuilt`.

- [ ] **Step 11: Commit**

```bash
git add server/backend/app server/backend/tests
git commit -m "feat(server): JSON API, MQTT client, app wiring, and rebuild-rollup CLI"
```

---

### Task 5: Frontend project and formatting helpers

**Files:**
- Create: `server/frontend/package.json`
- Create: `server/frontend/vite.config.js`
- Create: `server/frontend/index.html`
- Create: `server/frontend/src/main.js`
- Create: `server/frontend/src/App.svelte` (placeholder, replaced in Task 6)
- Create: `server/frontend/src/lib/format.js`
- Create: `server/frontend/src/lib/format.test.js`
- Create: `server/frontend/src/lib/api.js`
- Create: `server/frontend/src/lib/poll.js`

**Interfaces:**
- Consumes: API JSON shapes from Task 4.
- Produces (ES modules):
  - `format.js`: `formatKwh(v: number|null): string`, `since(iso: string, nowMs?: number): string`, `windowLabel(period, startIso, endIso): string`, `bucketLabel(period, iso): string`, `tooltipTitle(period, iso): string`, `periodNoun(period): string`, `dateTime(iso): string`
  - `api.js`: `fetchDevices(): Promise<Device[]>`, `fetchConsumption(id, period, anchor|null): Promise<Consumption>`
  - `poll.js`: `poll(fn: () => void, ms: number): () => void` (returns stop)

- [ ] **Step 1: Create project files**

`server/frontend/package.json`:

```json
{
  "name": "meter-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run"
  }
}
```

Run (from `server/frontend`):

```bash
npm install --save-dev vite @sveltejs/vite-plugin-svelte svelte vitest
npm install chart.js
```

Expected: `package-lock.json` created, no errors. `svelte` major version is 5.

`server/frontend/vite.config.js`:

```js
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: { proxy: { '/api': 'http://localhost:8080' } },
  test: { environment: 'node' },
})
```

`server/frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="color-scheme" content="light dark" />
    <title>Meters</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

`server/frontend/src/main.js`:

```js
import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

mount(App, { target: document.getElementById('app') })
```

`server/frontend/src/app.css`: empty file for now (filled in Task 6).

`server/frontend/src/App.svelte` (placeholder):

```svelte
<h1>Meters</h1>
```

- [ ] **Step 2: Write the failing tests**

`server/frontend/src/lib/format.test.js`:

```js
import { describe, expect, it } from 'vitest'
import {
  bucketLabel, dateTime, formatKwh, periodNoun, since, tooltipTitle, windowLabel,
} from './format.js'

describe('formatKwh', () => {
  it('groups thousands and keeps up to 2 decimals', () => {
    expect(formatKwh(12456.8)).toBe('12,456.8')
    expect(formatKwh(8.912)).toBe('8.91')
    expect(formatKwh(0)).toBe('0')
  })
  it('shows a dash for missing values', () => {
    expect(formatKwh(null)).toBe('—')
    expect(formatKwh(undefined)).toBe('—')
  })
})

describe('since', () => {
  const now = Date.parse('2026-10-06T10:00:00Z')
  it('rounds to the largest unit', () => {
    expect(since('2026-10-06T09:59:30Z', now)).toBe('<1 min')
    expect(since('2026-10-06T17:55:00+08:00', now)).toBe('5 min')
    expect(since('2026-10-06T07:00:00Z', now)).toBe('3 h')
    expect(since('2026-10-04T10:00:00Z', now)).toBe('2 d')
  })
  it('treats future timestamps as now', () => {
    expect(since('2026-10-06T10:05:00Z', now)).toBe('<1 min')
  })
})

describe('windowLabel', () => {
  it('formats each period from the server-local date part', () => {
    expect(windowLabel('hour', '2026-10-06T00:00:00+08:00', '2026-10-07T00:00:00+08:00'))
      .toBe('Tue, Oct 6 2026')
    expect(windowLabel('day', '2026-10-01T00:00:00+08:00', '2026-11-01T00:00:00+08:00'))
      .toBe('October 2026')
    expect(windowLabel('week', '2026-07-20T00:00:00+08:00', '2026-10-12T00:00:00+08:00'))
      .toBe('Jul 20 – Oct 11 2026')
    expect(windowLabel('month', '2026-01-01T00:00:00+08:00', '2027-01-01T00:00:00+08:00'))
      .toBe('2026')
    expect(windowLabel('year', '2024-01-01T00:00:00+08:00', '2027-01-01T00:00:00+08:00'))
      .toBe('All years')
  })
  it('shows both years when a week window crosses New Year', () => {
    expect(windowLabel('week', '2025-12-08T00:00:00+08:00', '2026-03-02T00:00:00+08:00'))
      .toBe('Dec 8 2025 – Mar 1 2026')
  })
})

describe('bucket labels', () => {
  it('formats axis labels', () => {
    expect(bucketLabel('hour', '2026-10-06T14:00:00+08:00')).toBe('14:00')
    expect(bucketLabel('day', '2026-10-06T00:00:00+08:00')).toBe('6')
    expect(bucketLabel('week', '2026-10-05T00:00:00+08:00')).toBe('Oct 5')
    expect(bucketLabel('month', '2026-10-01T00:00:00+08:00')).toBe('Oct')
    expect(bucketLabel('year', '2026-01-01T00:00:00+08:00')).toBe('2026')
  })
  it('formats tooltip titles', () => {
    expect(tooltipTitle('hour', '2026-10-06T14:00:00+08:00')).toBe('Oct 6, 14:00–15:00')
    expect(tooltipTitle('day', '2026-10-06T00:00:00+08:00')).toBe('Tue, Oct 6')
    expect(tooltipTitle('week', '2026-10-05T00:00:00+08:00')).toBe('Week of Oct 5')
    expect(tooltipTitle('month', '2026-10-01T00:00:00+08:00')).toBe('October 2026')
    expect(tooltipTitle('year', '2026-01-01T00:00:00+08:00')).toBe('2026')
  })
})

describe('misc', () => {
  it('periodNoun', () => {
    expect(periodNoun('hour')).toBe('this day')
    expect(periodNoun('day')).toBe('this month')
    expect(periodNoun('week')).toBe('these 12 weeks')
    expect(periodNoun('month')).toBe('this year')
    expect(periodNoun('year')).toBe('in total')
  })
  it('dateTime', () => {
    expect(dateTime('2026-10-06T10:58:12+08:00')).toBe('Oct 6, 10:58')
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd server/frontend && npm test`
Expected: FAIL, cannot resolve `./format.js`.

- [ ] **Step 4: Implement `server/frontend/src/lib/format.js`**

```js
// Dates from the API carry the server's offset. Labels use the date and time text as written,
// so they show server-local time no matter what zone the phone is in.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const kwh = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function formatKwh(v) {
  return v == null ? '—' : kwh.format(v)
}

export function since(iso, nowMs = Date.now()) {
  const s = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 1000))
  if (s < 60) return '<1 min'
  if (s < 3600) return `${Math.floor(s / 60)} min`
  if (s < 86400) return `${Math.floor(s / 3600)} h`
  return `${Math.floor(s / 86400)} d`
}

function parts(iso, dayOffset = 0) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const t = new Date(Date.UTC(y, m - 1, d + dayOffset))
  return { y: t.getUTCFullYear(), m: t.getUTCMonth(), d: t.getUTCDate(), dow: t.getUTCDay() }
}

const short = (p) => `${MONTHS[p.m]} ${p.d}`

export function windowLabel(period, startIso, endIso) {
  const s = parts(startIso)
  switch (period) {
    case 'hour': return `${DAYS[s.dow]}, ${short(s)} ${s.y}`
    case 'day': return `${MONTHS_LONG[s.m]} ${s.y}`
    case 'week': {
      const e = parts(endIso, -1)
      return s.y === e.y ? `${short(s)} – ${short(e)} ${e.y}` : `${short(s)} ${s.y} – ${short(e)} ${e.y}`
    }
    case 'month': return String(s.y)
    default: return 'All years'
  }
}

export function bucketLabel(period, iso) {
  const p = parts(iso)
  switch (period) {
    case 'hour': return iso.slice(11, 16)
    case 'day': return String(p.d)
    case 'week': return short(p)
    case 'month': return MONTHS[p.m]
    default: return String(p.y)
  }
}

export function tooltipTitle(period, iso) {
  const p = parts(iso)
  switch (period) {
    case 'hour': {
      const h = Number(iso.slice(11, 13))
      return `${short(p)}, ${String(h).padStart(2, '0')}:00–${String(h + 1).padStart(2, '0')}:00`
    }
    case 'day': return `${DAYS[p.dow]}, ${short(p)}`
    case 'week': return `Week of ${short(p)}`
    case 'month': return `${MONTHS_LONG[p.m]} ${p.y}`
    default: return String(p.y)
  }
}

const NOUNS = { hour: 'this day', day: 'this month', week: 'these 12 weeks', month: 'this year' }

export function periodNoun(period) {
  return NOUNS[period] ?? 'in total'
}

export function dateTime(iso) {
  return `${short(parts(iso))}, ${iso.slice(11, 16)}`
}
```

- [ ] **Step 5: Implement `server/frontend/src/lib/api.js` and `poll.js`**

`server/frontend/src/lib/api.js`:

```js
async function getJson(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`)
  return res.json()
}

export function fetchDevices() {
  return getJson('/api/devices')
}

export function fetchConsumption(id, period, anchor) {
  const q = new URLSearchParams({ period })
  if (anchor) q.set('anchor', anchor)
  return getJson(`/api/devices/${encodeURIComponent(id)}/consumption?${q}`)
}
```

`server/frontend/src/lib/poll.js`:

```js
// Calls fn every `ms` while the page is visible, and right away when it becomes visible again.
// Returns a function that stops polling.
export function poll(fn, ms) {
  const visible = () => document.visibilityState === 'visible'
  const timer = setInterval(() => { if (visible()) fn() }, ms)
  const onChange = () => { if (visible()) fn() }
  document.addEventListener('visibilitychange', onChange)
  return () => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', onChange)
  }
}
```

- [ ] **Step 6: Run tests and build**

Run: `cd server/frontend && npm test`
Expected: all tests pass.

Run: `cd server/frontend && npm run build`
Expected: `dist/index.html` written, no errors.

- [ ] **Step 7: Commit**

```bash
git add server/frontend/package.json server/frontend/package-lock.json server/frontend/vite.config.js server/frontend/index.html server/frontend/src
git commit -m "feat(web): Svelte project, API client, polling, and label formatting"
```

---

### Task 6: Frontend screens

**Files:**
- Modify: `server/frontend/src/App.svelte`
- Modify: `server/frontend/src/app.css`
- Create: `server/frontend/src/lib/StatusBadge.svelte`
- Create: `server/frontend/src/lib/BarChart.svelte`
- Create: `server/frontend/src/routes/DeviceList.svelte`
- Create: `server/frontend/src/routes/DevicePage.svelte`

**Interfaces:**
- Consumes: `format.js`, `api.js`, `poll.js` from Task 5; API from Task 4.
- Produces: `StatusBadge` props `{ online: boolean|null, compact?: boolean }`; `BarChart` props `{ labels: string[], titles: string[], values: (number|null)[], unit: string }`.

- [ ] **Step 1: Write `server/frontend/src/app.css`**

```css
:root {
  --bg: #f5f6f8;
  --card: #ffffff;
  --text: #15181b;
  --muted: #5d6873;
  --line: #e2e5e9;
  --accent: #0b6bcb;
  --accent-text: #ffffff;
  --online: #1a7f37;
  --warn-bg: #fff4d6;
  --warn-text: #6b4a00;
  --error-bg: #fde8e8;
  --error-text: #8a1c1c;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color-scheme: light dark;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1215;
    --card: #181c20;
    --text: #e7e9ec;
    --muted: #9ba5ae;
    --line: #2a3036;
    --accent: #5aa2f0;
    --accent-text: #0f1215;
    --online: #3fb950;
    --warn-bg: #3a2f10;
    --warn-text: #f0d68a;
    --error-bg: #3b1717;
    --error-text: #f4b4b4;
  }
}

* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); -webkit-text-size-adjust: 100%; }
main { max-width: 640px; margin: 0 auto; padding: 0 16px 32px; }
button { font: inherit; color: inherit; }

.bar {
  position: sticky; top: 0; z-index: 1;
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; background: var(--bg); border-bottom: 1px solid var(--line);
}
.bar h1 { flex: 1; margin: 0; font-size: 1.125rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.back {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 44px; min-height: 44px; margin-left: -12px;
  color: var(--accent); font-size: 1.75rem; text-decoration: none;
}

.banner {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  margin: 12px 16px 0; padding: 10px 12px; border-radius: 8px;
  background: var(--error-bg); color: var(--error-text);
}
.banner button { min-height: 36px; padding: 0 12px; border: 0; border-radius: 6px; background: var(--card); }

.list { list-style: none; margin: 12px 0 0; padding: 0; border-radius: 12px; overflow: hidden; background: var(--card); }
.list li + li { border-top: 1px solid var(--line); }
.row {
  display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 2px 8px;
  min-height: 64px; padding: 10px 16px; color: inherit; text-decoration: none;
}
.row:active { background: var(--line); }
.row .title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row .sub { grid-column: 1; color: var(--muted); font-size: 0.875rem; }
.row .chev { grid-row: 1 / span 2; grid-column: 2; color: var(--muted); font-size: 1.5rem; }

.empty { margin-top: 48px; color: var(--muted); text-align: center; }

.badge { white-space: nowrap; font-size: 0.875rem; color: var(--muted); }
.badge.online { color: var(--online); }

.setup { display: inline-block; margin-top: 8px; padding: 8px 0; color: var(--accent); }

.segments {
  display: flex; gap: 4px; margin: 12px 0; padding: 4px;
  overflow-x: auto; border-radius: 10px; background: var(--card);
  scrollbar-width: none;
}
.segments button {
  flex: 1 0 auto; min-height: 40px; padding: 0 14px;
  border: 0; border-radius: 8px; background: transparent; cursor: pointer;
}
.segments button.active { background: var(--accent); color: var(--accent-text); font-weight: 600; }

.window { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.window span { font-weight: 600; text-align: center; }
.window button {
  min-width: 44px; min-height: 44px; border: 0; border-radius: 22px;
  background: var(--card); font-size: 1.5rem; cursor: pointer;
}
.window button:disabled { opacity: 0.35; cursor: default; }

.total { margin: 16px 0; }
.total .big { margin: 0; font-size: 2.5rem; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.total .unit { font-size: 1.25rem; font-weight: 600; color: var(--muted); }
.muted { margin: 4px 0; color: var(--muted); }
.diff { margin: 8px 0 0; font-variant-numeric: tabular-nums; }
.note { margin: 8px 0 0; padding: 8px 10px; border-radius: 8px; background: var(--warn-bg); color: var(--warn-text); font-size: 0.875rem; }

.chart { position: relative; height: 240px; margin: 8px 0 16px; padding: 8px; border-radius: 12px; background: var(--card); }

.skeleton { border-radius: 12px; background: var(--line); animation: pulse 1.2s ease-in-out infinite; }
.skeleton.line { height: 64px; margin-top: 12px; }
.skeleton.block { height: 240px; margin-top: 16px; }
@keyframes pulse { 50% { opacity: 0.5; } }
@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
```

- [ ] **Step 2: Write `server/frontend/src/lib/StatusBadge.svelte`**

```svelte
<script>
  let { online, compact = false } = $props()
  const label = $derived(online === true ? 'online' : online === false ? 'offline' : 'status unknown')
  const glyph = $derived(online === true ? '●' : online === false ? '○' : '◌')
</script>

<span class="badge" class:online={online === true} title={label}>
  <span aria-hidden="true">{glyph}</span>{#if compact}<span class="visually-hidden">{label}</span>{:else} {label}{/if}
</span>

<style>
  .visually-hidden {
    position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap;
  }
</style>
```

- [ ] **Step 3: Write `server/frontend/src/lib/BarChart.svelte`**

```svelte
<script>
  import { BarController, BarElement, CategoryScale, Chart, LinearScale, Tooltip } from 'chart.js'
  import { formatKwh } from './format.js'

  Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip)

  let { labels, titles, values, unit } = $props()
  let canvas
  let chart

  $effect(() => {
    const css = getComputedStyle(document.documentElement)
    const color = (name) => css.getPropertyValue(name).trim()
    chart = new Chart(canvas, {
      type: 'bar',
      data: { labels: [], datasets: [{ data: [], backgroundColor: color('--accent'), borderRadius: 3, maxBarThickness: 32 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => titles[items[0].dataIndex],
              label: (item) => `${formatKwh(item.parsed.y)} ${unit}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: color('--muted'), maxRotation: 0, autoSkip: true } },
          y: { beginAtZero: true, grid: { color: color('--line') }, ticks: { color: color('--muted') } },
        },
      },
    })
    return () => chart.destroy()
  })

  $effect(() => {
    chart.data.labels = labels
    chart.data.datasets[0].data = values
    chart.update()
  })
</script>

<div class="chart">
  <canvas bind:this={canvas} role="img" aria-label="Consumption per period"></canvas>
</div>
```

- [ ] **Step 4: Write `server/frontend/src/routes/DeviceList.svelte`**

```svelte
<script>
  import { fetchDevices } from '../lib/api.js'
  import { formatKwh, since } from '../lib/format.js'
  import { poll } from '../lib/poll.js'
  import StatusBadge from '../lib/StatusBadge.svelte'

  let devices = $state(null)
  let error = $state(false)
  let now = $state(Date.now())

  async function load() {
    try {
      devices = await fetchDevices()
      error = false
    } catch {
      error = true
    }
    now = Date.now()
  }

  $effect(() => {
    load()
    return poll(load, 30000)
  })

  function detail(d) {
    const value = d.last_value == null ? 'No reading yet' : `${formatKwh(d.last_value)} kWh`
    const t = since(d.last_seen, now)
    return `${value} · ${d.online === false ? `offline ${t}` : `${t} ago`}`
  }
</script>

<header class="bar"><h1>Meters</h1></header>
{#if error}
  <div class="banner" role="alert">Couldn't load. <button onclick={load}>Retry</button></div>
{/if}
<main>
  {#if devices === null}
    {#if !error}
      <div class="skeleton line"></div>
      <div class="skeleton line"></div>
    {/if}
  {:else if devices.length === 0}
    <p class="empty">No meters yet. Devices appear here once they connect to the MQTT broker.</p>
  {:else}
    <ul class="list">
      {#each devices as d (d.id)}
        <li>
          <a class="row" href="#/device/{encodeURIComponent(d.id)}">
            <span class="title"><StatusBadge online={d.online} compact /> {d.name ?? d.id}</span>
            <span class="sub">{detail(d)}</span>
            <span class="chev" aria-hidden="true">›</span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</main>
```

- [ ] **Step 5: Write `server/frontend/src/routes/DevicePage.svelte`**

```svelte
<script>
  import { fetchConsumption, fetchDevices } from '../lib/api.js'
  import { bucketLabel, dateTime, formatKwh, periodNoun, tooltipTitle, windowLabel } from '../lib/format.js'
  import { poll } from '../lib/poll.js'
  import BarChart from '../lib/BarChart.svelte'
  import StatusBadge from '../lib/StatusBadge.svelte'

  let { id } = $props()

  const PERIODS = [['hour', 'Hourly'], ['day', 'Daily'], ['week', 'Weekly'], ['month', 'Monthly'], ['year', 'Yearly']]

  let period = $state('hour')
  let anchor = $state(null) // null = today (server decides)
  let data = $state(null)
  let device = $state(null)
  let error = $state(false)

  async function load() {
    const p = period
    const a = anchor
    try {
      const [consumption, devices] = await Promise.all([fetchConsumption(id, p, a), fetchDevices()])
      if (p !== period || a !== anchor) return // a newer request owns the screen
      data = consumption
      device = devices.find((d) => d.id === id) ?? null
      error = false
    } catch {
      error = true
    }
  }

  $effect(() => {
    period
    anchor
    load()
  })

  $effect(() => poll(load, 30000))

  const chart = $derived(data && {
    labels: data.buckets.map((b) => bucketLabel(data.period, b.start)),
    titles: data.buckets.map((b) => tooltipTitle(data.period, b.start)),
    values: data.buckets.map((b) => b.consumption),
  })
</script>

<header class="bar">
  <a class="back" href="#/" aria-label="All meters">‹</a>
  <h1>{device?.name ?? id}</h1>
  {#if device}<StatusBadge online={device.online} />{/if}
</header>
{#if error}
  <div class="banner" role="alert">Couldn't load. <button onclick={load}>Retry</button></div>
{/if}
<main>
  {#if device?.ip}
    <a class="setup" href="http://{device.ip}/" target="_blank" rel="noopener">Setup page ↗</a>
  {/if}

  <div class="segments" role="tablist" aria-label="Partition">
    {#each PERIODS as [p, label] (p)}
      <button role="tab" aria-selected={period === p} class:active={period === p} onclick={() => (period = p)}>
        {label}
      </button>
    {/each}
  </div>

  {#if data}
    <nav class="window" aria-label="Time window">
      <button aria-label="Previous" disabled={!data.prev_anchor} onclick={() => (anchor = data.prev_anchor)}>‹</button>
      <span>{windowLabel(data.period, data.window_start, data.window_end)}</span>
      <button aria-label="Next" disabled={!data.next_anchor} onclick={() => (anchor = data.next_anchor)}>›</button>
    </nav>

    <section class="total">
      <p class="big">{formatKwh(data.total)} <span class="unit">{data.unit}</span></p>
      <p class="muted">used {periodNoun(data.period)}</p>
      {#if data.differential}
        <p class="diff">{formatKwh(data.differential.start_value)} → {formatKwh(data.differential.end_value)} {data.unit}</p>
      {/if}
      {#if data.has_reset}
        <p class="note">Meter reset in this period. Total excludes the jump.</p>
      {/if}
    </section>

    <BarChart labels={chart.labels} titles={chart.titles} values={chart.values} unit={data.unit} />

    {#if data.current}
      <p class="muted">Meter now: {formatKwh(data.current.value)} {data.unit} · {dateTime(data.current.ts)}</p>
    {/if}
  {:else if !error}
    <div class="skeleton line"></div>
    <div class="skeleton block"></div>
  {/if}
</main>
```

- [ ] **Step 6: Replace `server/frontend/src/App.svelte`**

```svelte
<script>
  import DeviceList from './routes/DeviceList.svelte'
  import DevicePage from './routes/DevicePage.svelte'

  const PREFIX = '#/device/'
  let hash = $state(location.hash)

  $effect(() => {
    const onChange = () => (hash = location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  })

  const deviceId = $derived(hash.startsWith(PREFIX) ? decodeURIComponent(hash.slice(PREFIX.length)) : null)
</script>

{#if deviceId}
  {#key deviceId}
    <DevicePage id={deviceId} />
  {/key}
{:else}
  <DeviceList />
{/if}
```

- [ ] **Step 7: Build and run unit tests**

Run: `cd server/frontend && npm test && npm run build`
Expected: tests pass; build finishes with no Svelte compile errors or a11y warnings.

- [ ] **Step 8: Check against the real API with fake data**

Terminal 1 (from `server/backend`): seed a dev database and run the API without a broker:

```bash
uv run python -c "
import json, time
from app import db
from app.ingest import handle_message
c = db.connect('dev.db'); now = int(time.time()); v = 1000.0
handle_message(c, 'meter', 'meter/meter-dev000000001/status', b'{\"online\":true,\"ip\":\"127.0.0.1\"}', now)
for i in range(48 * 4):
    t = now - (48 * 4 - i) * 900; v += 0.2 + (i % 7) * 0.05
    handle_message(c, 'meter', 'meter/meter-dev000000001/reading', json.dumps({'ok': True, 'status': 'ok', 'raw': '', 'value': v}).encode(), t)
"
DB_PATH=dev.db MQTT_URL=mqtt://127.0.0.1:1 uv run uvicorn app.main:app --port 8080
```

(The MQTT connect fails and retries in the background; the API still serves.)

Terminal 2: `cd server/frontend && npm run dev`, open the printed URL, set the browser
devtools to a 390 px wide phone viewport, and check:
- list shows `meter-dev000000001` with ● and a kWh value; tapping opens the device page;
- Hourly shows bars for today, ‹ goes to yesterday, › is disabled on today;
- Daily, Weekly, Monthly, Yearly each render bars and a window label;
- total, start → end line, and "Meter now" are shown; no horizontal page scroll.

Stop both processes and delete `server/backend/dev.db*`.

- [ ] **Step 9: Commit**

```bash
git add server/frontend/src
git commit -m "feat(web): device list and device consumption page"
```

---

### Task 7: Docker deployment, fake devices, and docs

**Files:**
- Create: `server/Dockerfile`
- Create: `server/.dockerignore`
- Create: `server/docker-compose.yml`
- Create: `server/mosquitto.conf`
- Create: `server/backend/scripts/fake_meter.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: backend `app.main:app`, frontend `npm run build` output `dist/`.
- Produces: `docker compose up -d` stack on ports 1883 and 8080; `uv run python scripts/fake_meter.py`.

- [ ] **Step 1: Write `server/backend/scripts/fake_meter.py`**

```python
"""Publish simulated meter devices to an MQTT broker, for development.

    uv run python scripts/fake_meter.py --devices 2 --interval 5

Each device sends a retained online status, registers an offline last will, and publishes a rising
reading every interval. Ctrl+C marks the devices offline. Kill the process hard (or stop the
container network) to see the broker deliver the last will instead.
"""
import argparse
import json
import random
import time
from urllib.parse import urlparse

import paho.mqtt.client as mqtt


def make_client(device_id: str, host: str, port: int, prefix: str) -> mqtt.Client:
    status_topic = f"{prefix}/{device_id}/status"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=device_id)
    client.will_set(status_topic, json.dumps({"online": False}), qos=1, retain=True)

    def on_connect(c, userdata, flags, reason_code, properties):
        c.publish(status_topic, json.dumps({"online": True, "ip": "127.0.0.1"}), qos=1, retain=True)

    client.on_connect = on_connect
    client.connect(host, port, keepalive=30)
    client.loop_start()
    return client


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="mqtt://localhost:1883")
    parser.add_argument("--prefix", default="meter")
    parser.add_argument("--devices", type=int, default=2)
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between readings")
    parser.add_argument("--rate", type=float, default=1.5, help="average kWh per hour")
    parser.add_argument("--reset-every", type=int, default=0,
                        help="send a 'reset' reading every N readings (0 = never)")
    parser.add_argument("--dropout", type=float, default=0.0,
                        help="probability of skipping a reading")
    args = parser.parse_args()

    u = urlparse(args.url)
    host, port = u.hostname or "localhost", u.port or 1883
    ids = [f"meter-fa4e{n:08x}" for n in range(1, args.devices + 1)]
    clients = {i: make_client(i, host, port, args.prefix) for i in ids}
    values = {i: random.uniform(1000, 5000) for i in ids}
    started = time.monotonic()
    n = 0
    print(f"publishing {len(ids)} devices to {host}:{port}: {', '.join(ids)}")
    try:
        while True:
            n += 1
            for device_id, client in clients.items():
                if random.random() < args.dropout:
                    continue
                status = "ok"
                if args.reset_every and n % args.reset_every == 0:
                    values[device_id] = random.uniform(0, 10)
                    status = "reset"
                else:
                    values[device_id] += args.rate * args.interval / 3600 * random.uniform(0.5, 1.5)
                payload = {"ok": True, "status": status, "raw": f"{values[device_id]:.3f}",
                           "value": round(values[device_id], 3), "min_conf": 0.97, "dx": 0,
                           "dy": 0, "uptime_s": int(time.monotonic() - started)}
                client.publish(f"{args.prefix}/{device_id}/reading", json.dumps(payload), qos=1)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        for device_id, client in clients.items():
            client.publish(f"{args.prefix}/{device_id}/status", json.dumps({"online": False}),
                           qos=1, retain=True).wait_for_publish(2)
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the Docker files**

`server/Dockerfile`:

```dockerfile
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=web /web/dist ./static
ENV PATH="/app/.venv/bin:$PATH" STATIC_DIR=/app/static
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`server/.dockerignore`:

```
frontend/node_modules
frontend/dist
backend/.venv
backend/*.db*
**/__pycache__
```

`server/mosquitto.conf`:

```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
```

`server/docker-compose.yml`:

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - mosquitto-data:/mosquitto/data
    restart: unless-stopped

  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      MQTT_URL: mqtt://mosquitto:1883
      MQTT_PREFIX: meter
      DB_PATH: /data/meter.db
      TZ: Asia/Manila
    volumes:
      - app-data:/data
    depends_on:
      - mosquitto
    restart: unless-stopped

volumes:
  mosquitto-data:
  app-data:
```

- [ ] **Step 3: Build and start the stack**

Run: `cd server && docker compose up -d --build`
Expected: both containers running (`docker compose ps` shows `mosquitto` and `app` up).

Run: `curl -s http://localhost:8080/api/devices`
Expected: `[]` (or existing devices).

- [ ] **Step 4: End-to-end check with fake devices**

Run (from `server/backend`): `uv run python scripts/fake_meter.py --devices 2 --interval 3 --reset-every 40`

In a browser at `http://localhost:8080/` with a 390 px wide viewport:
- both `meter-fa4e...` devices appear with ● online within 30 s;
- the device page shows a non-zero Hourly bar for the current hour and the total grows on refresh;
- after the 40th reading the "Meter reset in this period" note appears and the total does not jump.

Stop `fake_meter.py` with Ctrl+C. Within 30 s both devices show ○ offline.

Start it again, then kill it hard (`taskkill /F /IM python.exe` on Windows only if no other Python
processes matter, or close the terminal). Within about 45 s plus one poll, the devices show
offline again via the last will.

Run: `docker compose restart app` and reload the page: devices and history are still there.

- [ ] **Step 5: Document the server in `README.md`**

Update the layout block at the top to:

```
training/   Python: synthetic data, training, int8 export, crop collection
firmware/   ESP-IDF project: camera, alignment, inference, plausibility checks, web setup, MQTT
server/     Docker Compose: Mosquitto broker + FastAPI/SQLite service + mobile web app
data/real/  Labeled real crops, one folder per class (0-9, blank, unsure)
```

Add after the `## MQTT` section:

````markdown
## Server

Needs Docker with Compose.

```sh
cd server
docker compose up -d --build
```

This starts Mosquitto on port 1883 and the web app on http://<host>:8080/. Point each device's
`METER_MQTT_URI` at `mqtt://<host>:1883`. Devices appear in the app on their first status message
or reading. Set `TZ` in `docker-compose.yml` to your time zone; consumption is bucketed in that zone.

The app stores every reading in SQLite (`app-data` volume) and keeps an hourly consumption
rollup. Consumption is the sum of increases between accepted readings; a `reset` reading starts a
new baseline. After changing that rule, rebuild the rollup:

```sh
docker compose exec app python -m app.cli rebuild-rollup
```

Development without hardware:

```sh
cd server/backend
uv sync
uv run pytest
uv run python scripts/fake_meter.py --devices 2     # needs the broker from docker compose
cd ../frontend
npm install
npm test
npm run dev                                          # proxies /api to localhost:8080
```
````

- [ ] **Step 6: Run every test suite once more**

Run: `cd server/backend && uv run pytest -q`
Expected: all pass.

Run: `cd server/frontend && npm test`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add server/Dockerfile server/.dockerignore server/docker-compose.yml server/mosquitto.conf server/backend/scripts/fake_meter.py README.md
git commit -m "feat(server): Docker Compose deployment, fake devices, and docs"
```

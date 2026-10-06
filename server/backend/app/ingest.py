"""MQTT message parsing and storage."""
import json
import logging
import os
import time
from urllib.parse import unquote, urlparse

import paho.mqtt.client as mqtt

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

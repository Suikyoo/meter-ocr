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

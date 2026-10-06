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

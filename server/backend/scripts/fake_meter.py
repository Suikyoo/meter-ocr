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

"""Pull digit crops from a running device into data/unlabeled/<predicted class>/.

Review the folders, move wrong crops into the right class folder, then move the
reviewed folders into data/real/ and retrain.

Usage:
    uv run python collect.py --host 192.168.1.50 --every 60
"""
import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from common import CLASSES

ROOT = Path(__file__).resolve().parent.parent


def fetch(host):
    with urllib.request.urlopen(f"http://{host}/api/crops", timeout=10) as res:
        return json.load(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--every", type=int, default=60, help="seconds between polls")
    ap.add_argument("--out", default=str(ROOT / "data" / "unlabeled"))
    ap.add_argument("--all", action="store_true",
                    help="save every reading, not only failed or low-confidence ones")
    ap.add_argument("--conf", type=float, default=0.95,
                    help="save a reading if any digit is below this confidence")
    args = ap.parse_args()
    out = Path(args.out)

    last_uptime = None
    while True:
        try:
            r = fetch(args.host)
        except OSError as e:
            print(f"fetch failed: {e}")
            time.sleep(args.every)
            continue

        fresh = r.get("uptime_s") != last_uptime
        last_uptime = r.get("uptime_s")
        interesting = not r["ok"] or any(d["conf"] < args.conf for d in r.get("digits", []))
        if fresh and r.get("digits") and (args.all or interesting):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for i, d in enumerate(r["digits"]):
                px = np.frombuffer(base64.b64decode(d["pixels"]), np.uint8)
                img = px.reshape(r["height"], r["width"])
                folder = out / CLASSES[d["cls"]]
                folder.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(folder / f"{stamp}_{i}.png"), img)
            print(f"{stamp} saved {len(r['digits'])} crops ({r['status']} raw={r['raw']})")
        time.sleep(args.every)


if __name__ == "__main__":
    main()

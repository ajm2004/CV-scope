"""Download the CC-BY-4.0 sample videos used in the documentation.

Usage: python scripts/download_samples.py [--dest samples/videos]
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = "https://github.com/intel-iot-devkit/sample-videos/raw/master/"
FILES = ["people-detection.mp4", "person-bicycle-car-detection.mp4"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=str(Path(__file__).resolve().parents[1] / "samples" / "videos"))
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / name
        if target.exists() and target.stat().st_size > 0:
            print(f"exists  {target}")
            continue
        url = BASE + name
        print(f"download {url}")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, open(target, "wb") as fh:  # noqa: S310
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"failed  {name}: {exc}", file=sys.stderr)
            target.unlink(missing_ok=True)
            return 1
        print(f"saved   {target} ({target.stat().st_size / 1e6:.1f} MB)")
    print("Attribution: Intel IoT DevKit sample videos, CC-BY-4.0 (https://github.com/intel-iot-devkit/sample-videos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

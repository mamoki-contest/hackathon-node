"""SENTRY-X 허브 러너 — USB 폴백판 (Slice 1/2, MQTT 우회).

USB 수집기 → 구역 융합기 → 콘솔 구역 점등. MQTT판(main.py)과 융합기·표시는 동일.
ESPectre 정규화 점수(mvmt/thr) 기준이라 임계값 1.0 사용.

실행: .venv/bin/python hub/main_usb.py            (계속)
      .venv/bin/python hub/main_usb.py --seconds 18  (18초 후 종료, 캡처용)
"""

from __future__ import annotations
import argparse
import os
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_usb import SerialIngest     # noqa: E402
from zone_fusion import ZoneFusion      # noqa: E402

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def render(zone_states):
    cells = []
    for zone, s in zone_states.items():
        if not s.reporting:
            cells.append(f"[{zone}: --무신호--]")
        elif s.active:
            cells.append(f"[{zone}: ●활성 {s.intensity:4.2f}]")
        else:
            cells.append(f"[{zone}: ·정지 {s.intensity:4.2f}]")
    return "  ".join(cells)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem101")
    ap.add_argument("--node", default="node1", help="이 USB 노드를 어느 노드로 볼지")
    ap.add_argument("--seconds", type=float, default=0, help="0이면 무한")
    ap.add_argument("--newline", action="store_true", help="갱신 시 새 줄(캡처용)")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    # ESPectre 정규화 점수(mvmt/thr) 기준 → 임계값 1.0
    fus = ZoneFusion(node_zone=cfg["nodes"], zones=cfg["zones"],
                     threshold=1.0, ema_alpha=cfg["fusion"]["ema_alpha"],
                     stale_after_s=cfg["fusion"]["stale_after_s"])
    ing = SerialIngest(port=args.port, node_id=args.node,
                       on_signal=lambda n, s, t: fus.update(n, s, time.time()))
    ing.start_async()
    print(f"SENTRY-X 허브(USB) 시작. node={args.node} → 구역 표시 (Ctrl+C 종료)\n")
    t0 = time.time()
    try:
        while True:
            line = render(fus.zone_states(now=time.time()))
            print(line if args.newline else "\r" + line,
                  end=("\n" if args.newline else ""), flush=True)
            if args.seconds and time.time() - t0 > args.seconds:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ing.stop()
        print("\n종료.")


if __name__ == "__main__":
    main()

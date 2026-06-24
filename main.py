"""SENTRY-X 허브 러너 (콘솔 스코프) — Slice 1/2 엔드투엔드.

⚠️ 이 코드는 노트북(허브)에서 돈다. ESP32 펌웨어가 아니다.
신호 수집기(MQTT) → 구역 융합기 → 콘솔에 좌/중/우 구역 점등 표시.
의사 열화상/오버레이(Slice 3~5)는 별도. 이건 WiFi 트랙 검증용 최소 스코프.

실행: .venv/bin/python hub/main.py
"""

from __future__ import annotations
import os
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import SignalIngest          # noqa: E402
from zone_fusion import ZoneFusion       # noqa: E402

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config(path=CONFIG):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render(zone_states):
    """구역 상태를 한 줄 막대로 표시."""
    cells = []
    for zone, s in zone_states.items():
        if not s.reporting:
            mark = f"[{zone}: --무신호--]"
        elif s.active:
            mark = f"[{zone}: ●활성 {s.intensity:4.1f}]"
        else:
            mark = f"[{zone}: ·정지 {s.intensity:4.1f}]"
        cells.append(mark)
    return "  ".join(cells)


def main():
    cfg = load_config()
    fus = ZoneFusion(
        node_zone=cfg["nodes"],
        zones=cfg["zones"],
        threshold=cfg["fusion"]["threshold"],
        ema_alpha=cfg["fusion"]["ema_alpha"],
        stale_after_s=cfg["fusion"]["stale_after_s"],
    )
    ing = SignalIngest(
        broker=cfg["mqtt"]["broker"],
        port=cfg["mqtt"]["port"],
        topic=cfg["mqtt"]["topic"],
        on_signal=lambda nid, score, ts: fus.update(nid, score, time.time()),
    )
    ing.start_async()
    print("SENTRY-X 허브 시작. 구역 상태 표시 중 (Ctrl+C 종료)\n")
    try:
        while True:
            print("\r" + render(fus.zone_states(now=time.time())), end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        ing.stop()
        print("\n종료.")


if __name__ == "__main__":
    main()

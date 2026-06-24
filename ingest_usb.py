"""① 신호 수집기 — USB 폴백 어댑터 (MQTT 대신).

핫스팟 격리(AP isolation)로 MQTT가 막힐 때 사용. ESPectre가 USB 시리얼 로그에
뿌리는 모션 점수를 읽어, MQTT 수집기와 '똑같은' on_signal(node_id, score, ts)
형식으로 융합기에 넘긴다. → 융합기·화면은 손대지 않는다(심 설계 그대로).

ESPectre 로그 예:
  [I][espectre:412][wifi]: [...] | mvmt:5.5731 thr:3.4243 | MOTION | 100 pkt/s | ...

정규화 점수 = mvmt / thr  (ESPectre의 자동 임계값 기준 → 1.0 넘으면 움직임).
"""

from __future__ import annotations
import re
import threading
import time

import serial

LINE = re.compile(r"mvmt:([0-9.]+)\s+thr:([0-9.]+)\s*\|\s*(MOTION|IDLE)")


class SerialIngest:
    """USB 시리얼에서 ESPectre 모션 점수를 읽어 콜백으로 흘려보낸다."""

    def __init__(self, port="/dev/cu.usbmodem101", node_id="node1",
                 baud=115200, on_signal=None):
        self.port = port
        self.node_id = node_id
        self.baud = baud
        self.on_signal = on_signal or (lambda *_: None)
        self._run = False
        self._thread = None

    def _reader(self):
        s = serial.Serial(self.port, self.baud, timeout=1)
        print(f"[ingest_usb] {self.port} 읽는 중 (node={self.node_id})")
        while self._run:
            try:
                raw = s.readline().decode("utf-8", "replace")
            except serial.SerialException:
                break
            m = LINE.search(raw)
            if not m:
                continue
            mvmt, thr = float(m.group(1)), float(m.group(2))
            score = mvmt / thr if thr > 0 else 0.0   # 1.0 넘으면 ESPectre가 MOTION 판정
            self.on_signal(self.node_id, score, time.time())
        s.close()

    def start_async(self):
        self._run = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self):
        self._run = False

"""⑤ 풀 스코프 (투시 오버레이) + ④ 사람검출 + ③ 의사열화상 + WiFi 구역 점등.

한 화면에서:
  - 웹캠 → 열화상 컬러맵 (Slice 3)
  - YOLO 사람 검출 박스 (Slice 4)
  - WiFi 노드(USB)에서 온 구역 상태를 좌/중/우 세로 스트립으로 점등 (Slice 5)
  - 보너스: 교차경보 배너 (의심/사람확정, Slice 6 맛보기)

WiFi 트랙(ESP32 USB) + 비전 트랙(웹캠)이 합류하는 지점.
실행: .venv/bin/python hub/scope_full.py   (창에서 q 종료)
※ macOS 카메라 권한 허용 필요. ESP32는 USB로 꽂혀 있어야 구역이 점등됨.
"""

from __future__ import annotations
import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np
import yaml
from ultralytics import YOLO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_usb import SerialIngest      # noqa: E402
from zone_fusion import ZoneFusion       # noqa: E402

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
PERSON_CLASS = 0
CONF = 0.4


def discover_usb_nodes():
    """꽂힌 USB 보드들을 찾아 node_id에 매핑.
    1대 → node1(좌), 2대 → node1(좌)+node3(우), 3대 → node1/2/3(좌/중/우).
    (config.yaml: node1=left, node2=center, node3=right)
    """
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if len(ports) >= 3:
        ids = ["node1", "node2", "node3"]
    elif len(ports) == 2:
        ids = ["node1", "node3"]      # 좌 / 우
    else:
        ids = ["node1"]
    return list(zip(ports, ids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0,
                    help="카메라 번호. 아이폰(연속성)이 0번이면 1, 2 로 바꿔 맥북 내장 선택")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    zones = cfg["zones"]
    fus = ZoneFusion(node_zone=cfg["nodes"], zones=zones,
                     threshold=1.0, ema_alpha=cfg["fusion"]["ema_alpha"],
                     stale_after_s=cfg["fusion"]["stale_after_s"])
    pairs = discover_usb_nodes()
    if not pairs:
        print("USB 보드를 못 찾음 — ESP32 연결 확인")
    ings = []
    for port, nid in pairs:
        ig = SerialIngest(port=port, node_id=nid,
                          on_signal=lambda n, s, t: fus.update(n, s, time.time()))
        ig.start_async()
        ings.append(ig)
        print(f"  {port} → {nid}")

    print("YOLO 로드...")
    model = YOLO("yolov8n.pt")

    cap = cv2.VideoCapture(args.cam)
    if not cap.isOpened():
        print(f"카메라 {args.cam} 열기 실패 — --cam 1 또는 2 로 시도")
        sys.exit(1)
    print(f"카메라 {args.cam} 사용")
    print("카메라 워밍업...")
    for _ in range(30):
        ok, _f = cap.read()
        if ok:
            break
        time.sleep(0.1)

    print("풀 스코프 시작 (창에서 q 종료)")
    fps_t, fps_n, fps, fails = time.time(), 0, 0.0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            fails += 1
            if fails > 30:
                break
            time.sleep(0.05)
            continue
        fails = 0
        frame = cv2.flip(frame, 1)      # 거울 모드(좌우반전) — 셀카처럼 자연스럽게
        H, W = frame.shape[:2]

        # ④ 사람 검출 (원본 RGB)
        res = model(frame, classes=[PERSON_CLASS], conf=CONF, verbose=False)
        boxes = res[0].boxes
        n_person = len(boxes)

        # ③ 의사 열화상
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        view = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)

        # ⑤ WiFi 구역 오버레이 (세로 3등분)
        states = fus.zone_states(now=time.time())
        overlay = view.copy()
        colw = W // len(zones)
        any_motion = False
        for i, z in enumerate(zones):
            x0, x1 = i * colw, (i + 1) * colw if i < len(zones) - 1 else W
            s = states[z]
            if not s.reporting:
                color, alpha, tag = (90, 90, 90), 0.12, "NO SIGNAL"
            elif s.active:
                color, alpha, tag = (0, 0, 255), 0.40, "MOTION"
                any_motion = True
            else:
                color, alpha, tag = (0, 170, 0), 0.12, "clear"
            cv2.rectangle(overlay, (x0, 0), (x1, H), color, -1)
            cv2.line(view, (x1, 0), (x1, H), (255, 255, 255), 1)
            cv2.putText(view, f"{z.upper()}: {tag}", (x0 + 8, H - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        view = cv2.addWeighted(overlay, 0.35, view, 0.65, 0)

        # 사람 박스 (오버레이 위에)
        for b in boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            cv2.rectangle(view, (x1, y1), (x2, y2), (255, 255, 255), 2)
            cv2.putText(view, f"PERSON {float(b.conf[0]):.2f}", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # 교차경보 배너 (Slice 6 맛보기)
        if any_motion and n_person > 0:
            cue, ccol = "CONFIRMED: PERSON", (0, 0, 255)
        elif any_motion:
            cue, ccol = "SUSPECT: motion (no visual)", (0, 165, 255)
        else:
            cue, ccol = "CLEAR", (0, 200, 0)

        # 상태바
        fps_n += 1
        if time.time() - fps_t >= 1.0:
            fps, fps_n, fps_t = fps_n / (time.time() - fps_t), 0, time.time()
        cv2.rectangle(view, (0, 0), (W, 34), (0, 0, 0), -1)
        cv2.putText(view, f"SENTRY-X  | persons:{n_person} | {fps:.0f}fps", (10, 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(view, cue, (W - 360, 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, ccol, 2)

        cv2.imshow("SENTRY-X Full Scope", view)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    for ig in ings:
        ig.stop()


if __name__ == "__main__":
    main()

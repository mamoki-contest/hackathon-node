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
    ap.add_argument("--mqtt", action="store_true",
                    help="USB 대신 MQTT로 노드 신호 수신 (무선/보조배터리). 브로커+노드가 mamoki에 있어야 함")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    zones = cfg["zones"]
    # USB: 점수 = mvmt/thr (임계 1.0). MQTT: raw mvmt를 노드별 기준선으로 정규화(임계 3.0).
    threshold = 3.0 if args.mqtt else 1.0
    fus = ZoneFusion(node_zone=cfg["nodes"], zones=zones,
                     threshold=threshold, ema_alpha=cfg["fusion"]["ema_alpha"],
                     stale_after_s=cfg["fusion"]["stale_after_s"])

    ings = []
    if args.mqtt:
        import subprocess
        from ingest import SignalIngest
        # 브로커(mosquitto) 자동 시작 — 안 켜져 있으면 직접 띄운다
        running = subprocess.run(
            ["bash", "-c", "lsof -nP -iTCP:1883 -sTCP:LISTEN | grep -q mosquitto"]
        ).returncode == 0
        if not running:
            conf = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "mosquitto.conf")
            subprocess.Popen(["/opt/homebrew/sbin/mosquitto", "-c", conf],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            print("  브로커(mosquitto) 자동 시작")
        else:
            print("  브로커 이미 실행중")
        mq = cfg["mqtt"]
        _base = {}

        def on_sig(nid, score, ts):
            # 노드마다 raw mvmt 스케일이 달라서, 조용할 때의 '바닥'을 추적해 배율로 정규화
            b = _base.get(nid, score)
            b = score if score < b else b * 0.999 + score * 0.001
            b = max(b, 1e-4)
            _base[nid] = b
            fus.update(nid, score / b, time.time())   # 기준선 대비 몇 배인지

        ig = SignalIngest(broker=mq["broker"], port=mq["port"],
                          topic=mq["topic"], on_signal=on_sig)
        ig.start_async()
        ings.append(ig)
        print(f"  MQTT {mq['broker']}:{mq['port']}  {mq['topic']}")
    else:
        pairs = discover_usb_nodes()
        if not pairs:
            print("USB 보드를 못 찾음 — ESP32 연결 확인")
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

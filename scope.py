"""③+④ 스코프 (의사 열화상 + 자동 사람 검출) — SENTRY-X 허브.

PRD Slice 3: 웹캠 프레임에 컬러맵(열화상 룩).
PRD Slice 4: 사람 검출은 컬러맵 입히기 *전* 원본 RGB 프레임에 돌린다(YOLO).
검출 박스는 열화상 화면 위에 그린다. 나중에 Slice 5에서 구역 오버레이를 여기에 합친다.

실행: .venv/bin/python hub/scope.py
종료: 창에서 q
※ 실행 시 macOS 카메라 권한 허용 필요.
"""

from __future__ import annotations
import sys
import time

import cv2
from ultralytics import YOLO

PERSON_CLASS = 0          # COCO에서 'person'
CONF = 0.4                # 검출 신뢰도 임계값 (Slice 7에서 라이브 튜닝)


def main():
    print("YOLO 모델 로드 중...")
    model = YOLO("yolov8n.pt")     # 최초 1회 자동 다운로드(~6MB)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("웹캠을 열 수 없음 — 카메라 권한/연결 확인")
        sys.exit(1)

    # 카메라 워밍업: 첫 프레임이 준비될 때까지 잠깐 기다린다(macOS 타이밍)
    print("카메라 워밍업...")
    warm_ok = False
    for _ in range(30):
        ok, _f = cap.read()
        if ok:
            warm_ok = True
            break
        time.sleep(0.1)
    if not warm_ok:
        print("카메라에서 프레임을 못 받음 — 다른 앱이 카메라 쓰는 중인지 확인")
        sys.exit(1)

    print("스코프 시작 (창에서 q 눌러 종료)")
    fps_t, fps_n, fps = time.time(), 0, 0.0
    fails = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            fails += 1
            if fails > 30:        # 연속 실패가 쌓이면 종료
                break
            time.sleep(0.05)
            continue
        fails = 0

        # ④ 사람 검출 — 원본 RGB 프레임에 (컬러맵 입히기 전)
        res = model(frame, classes=[PERSON_CLASS], conf=CONF, verbose=False)
        boxes = res[0].boxes

        # ③ 의사 열화상 — 원본을 그레이→컬러맵(INFERNO=열화상 룩)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        thermal = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)

        # 검출 박스를 열화상 위에 표시
        n_person = 0
        for b in boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            c = float(b.conf[0])
            n_person += 1
            cv2.rectangle(thermal, (x1, y1), (x2, y2), (255, 255, 255), 2)
            cv2.putText(thermal, f"PERSON {c:.2f}", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # 상단 상태바
        fps_n += 1
        if time.time() - fps_t >= 1.0:
            fps, fps_n, fps_t = fps_n / (time.time() - fps_t), 0, time.time()
        label = f"SENTRY-X SCOPE  |  persons: {n_person}  |  {fps:.0f} fps"
        cv2.rectangle(thermal, (0, 0), (thermal.shape[1], 30), (0, 0, 0), -1)
        cv2.putText(thermal, label, (10, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.imshow("SENTRY-X Scope", thermal)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

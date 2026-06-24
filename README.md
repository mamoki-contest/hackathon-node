# SENTRY-X — 허브 (노트북)

센싱 노드(ESP32/ESPectre)의 모션 신호를 받아 좌/중/우 구역으로 융합하고, 웹캠 의사 열화상 + 사람 검출(YOLO) + 투시 오버레이로 보여주는 스코프.

## 설치
```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 실행
```bash
# 풀 스코프 (열화상 + 사람검출 + WiFi 구역 점등)
.venv/bin/python scope_full.py            # USB 보드 자동 감지

# WiFi 구역만 (텍스트)
.venv/bin/python main_usb.py              # USB
.venv/bin/python main.py                  # MQTT (Mosquitto 필요)

# 단위 테스트
.venv/bin/python tests/test_zone_fusion.py
```

## 구성
| 파일 | 역할 |
|---|---|
| `ingest.py` / `ingest_usb.py` | ① 신호 수집기 (MQTT / USB) |
| `zone_fusion.py` | ② 구역 융합기 (좌/중/우 판정) |
| `scope_full.py` | ③④⑤ 의사열화상 + 사람검출 + 투시 오버레이 |
| `config.yaml` | 노드↔구역 매핑 |

## 메모
- 노드 펌웨어는 별도 저장소
- YOLO 모델(`yolov8n.pt`)은 첫 실행 시 자동 다운로드
- macOS 카메라 권한 필요 / 아이폰 연속성 카메라면 `--cam` 번호 조정

#!/bin/bash
# SENTRY-X MQTT 진단 — mamoki에 연결한 상태에서 실행하세요.
# 사용: bash ~/Desktop/sentry-x/hub/diag.sh
# 끝나면 인터넷 WiFi로 돌아가서 Claude에게 알려주세요 (결과는 /tmp/sentryx_diag.txt).
OUT=/tmp/sentryx_diag.txt
ROOT=~/Desktop/sentry-x
{
echo "=== SENTRY-X MQTT 진단 $(date) ==="
echo "노트북 WiFi: $(networksetup -getairportnetwork en0 2>/dev/null)"
echo "노트북 IP(en0): $(ipconfig getifaddr en0 2>/dev/null || echo 없음)"
echo "펌웨어 hub_ip: $(grep hub_ip $ROOT/nodes/secrets.yaml)"

# 브로커 실행 확인 / 없으면 시작
if lsof -nP -iTCP:1883 -sTCP:LISTEN 2>/dev/null | grep -q mosquitto; then
  echo "브로커: 이미 실행중"
else
  /opt/homebrew/sbin/mosquitto -c $ROOT/hub/mosquitto.conf -d 2>/dev/null
  echo "브로커: 새로 시작함"
  sleep 2
fi
} > "$OUT" 2>&1

# 15초간 노드 메시지 구독
$ROOT/.venv/bin/python - >> "$OUT" 2>&1 <<'PY'
import paho.mqtt.client as mqtt, time
got=[]
c=mqtt.Client()
c.on_connect=lambda cl,u,f,rc: cl.subscribe("sentryx/#")
c.on_message=lambda cl,u,m: got.append((m.topic, m.payload.decode('utf-8','replace')[:70]))
try:
    c.connect("127.0.0.1",1883,10); c.loop_start()
except Exception as e:
    print("브로커 연결 실패:", e); raise SystemExit
time.sleep(15); c.loop_stop()
print(f"MQTT 수신: {len(got)}건")
for t,p in got[:6]: print("  ", t, p)
PY

echo "=== 끝. 인터넷 WiFi로 돌아가 Claude에게 알려주세요 ===" >> "$OUT"
cat "$OUT"

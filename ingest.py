"""① 신호 수집기 (Signal Ingest) — MQTT 구독 + 정규화 심 어댑터.

PRD: 감지기 백엔드(ESPectre)가 발행하는 모션 신호를 받아 표준형
{node_id, motion_score, timestamp} 으로 정규화한다. 백엔드를 바꾸면
(esp-csi 자체구현 등) 이 어댑터만 교체하면 되고 허브 나머지는 불변.

ESPectre 노드는 토픽 `sentryx/node/<id>/motion` 에 JSON을 발행한다
(nodes/sentryx-node.yaml 의 mqtt.publish_json 참고).
"""

from __future__ import annotations
import json
import time

import paho.mqtt.client as mqtt


class SignalIngest:
    """MQTT에서 노드 모션 신호를 받아 콜백으로 흘려보낸다."""

    def __init__(self, broker="127.0.0.1", port=1883,
                 topic="sentryx/node/+/motion", on_signal=None):
        self.broker = broker
        self.port = port
        self.topic = topic
        # on_signal(node_id: str, motion_score: float, timestamp: float)
        self.on_signal = on_signal or (lambda *_: None)
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(self.topic)
        print(f"[ingest] 구독: {self.topic} (rc={rc})")

    def _on_message(self, client, userdata, msg):
        node_id, score, ts = self._normalize(msg)
        if node_id is None:
            return
        self.on_signal(node_id, score, ts)

    @staticmethod
    def _normalize(msg):
        """원시 MQTT 메시지 → (node_id, motion_score, timestamp) 표준형.

        ESPectre가 JSON을 보내면 그대로 파싱하고, 혹시 숫자만 오는 경우엔
        토픽에서 node_id를 뽑고 값만 점수로 쓴다(백엔드 차이 흡수).
        """
        payload = msg.payload.decode("utf-8", "replace").strip()
        try:
            d = json.loads(payload)
            node_id = str(d.get("node_id") or msg.topic.split("/")[2])
            score = float(d.get("motion_score"))
            ts = float(d.get("timestamp", time.time()))
            return node_id, score, ts
        except (ValueError, KeyError, IndexError, TypeError):
            # JSON이 아니면: 토픽 sentryx/node/<id>/motion 에서 id 추출 + 값만
            try:
                node_id = msg.topic.split("/")[2]
                return node_id, float(payload), time.time()
            except (ValueError, IndexError):
                return None, None, None

    def start(self):
        """블로킹 루프. 별도 스레드에서 돌리고 싶으면 loop_start() 사용."""
        self._client.connect(self.broker, self.port, keepalive=30)
        self._client.loop_forever()

    def start_async(self):
        self._client.connect(self.broker, self.port, keepalive=30)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

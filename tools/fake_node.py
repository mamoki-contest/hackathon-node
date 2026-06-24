"""가짜 노드 — 실제 ESP32 없이 허브를 테스트하기 위해 합성 모션 신호를 MQTT로 발행.

사용: .venv/bin/python hub/tools/fake_node.py node1 --moving
ESPectre 노드가 보내는 것과 동일한 토픽·JSON 형식으로 쏜다.
"""

from __future__ import annotations
import argparse
import json
import random
import time

import paho.mqtt.client as mqtt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("node_id", help="예: node1")
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--moving", action="store_true",
                    help="움직임 점수(높음) 발행. 없으면 기준선(잔잔).")
    args = ap.parse_args()

    cli = mqtt.Client()
    cli.connect(args.broker, args.port, 30)
    cli.loop_start()
    topic = f"sentryx/node/{args.node_id}/motion"
    print(f"발행: {topic}  ({'움직임' if args.moving else '기준선'}) — Ctrl+C 종료")
    try:
        while True:
            base = 2.0 if args.moving else 0.05
            score = round(base + random.uniform(-0.05, 0.3), 3)
            cli.publish(topic, json.dumps({
                "node_id": args.node_id,
                "motion_score": score,
                "timestamp": time.time(),
            }))
            time.sleep(0.1)
    except KeyboardInterrupt:
        cli.loop_stop()
        print("\n종료.")


if __name__ == "__main__":
    main()

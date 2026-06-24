"""② 구역 융합기 (Zone Fusion) — SENTRY-X 허브 딥모듈.

PRD: ESPectre가 탐지(신호처리)를 끝내므로 여기서는 신호처리를 하지 않고
'노드별 모션 신호 → 좌/중/우 구역 상태'로 매핑 + 임계값/평활화만 한다.
노드 수 유연(설정 기반 N노드): 2개면 좌/우, 3개면 좌/중/우.

이 모듈은 하드웨어·MQTT와 무관한 순수 로직이라 합성 신호로 단위 테스트한다
(PRD 「테스트 결정」이 지정한 테스트 대상).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ZoneState:
    active: bool          # 구역에 움직임이 있다고 판정됐는지
    intensity: float      # 평활화된 모션 강도 (0~)
    reporting: bool       # 이 구역에 신호를 보내는 노드가 살아있는지


class ZoneFusion:
    """노드별 모션 점수를 받아 구역 상태로 융합한다.

    update()로 노드 신호를 흘려넣고, zone_states()로 현재 구역 상태를 읽는다.
    """

    def __init__(self, node_zone, zones=None, threshold=0.5,
                 ema_alpha=0.4, stale_after_s=3.0):
        # node_zone: {node_id: zone}  (예: {"node1": "left", ...})
        self.node_zone = dict(node_zone)
        # zones: 표시 순서를 정하는 구역 리스트. 없으면 매핑에서 추출(등장 순서).
        if zones is None:
            zones = list(dict.fromkeys(node_zone.values()))
        self.zones = list(zones)
        self.threshold = threshold
        self.alpha = ema_alpha
        self.stale_after_s = stale_after_s
        self._ema = {}    # node_id -> 평활화된 점수
        self._last = {}   # node_id -> 마지막 timestamp

    def update(self, node_id, motion_score, timestamp=None):
        """노드 1개의 모션 점수를 반영. 설정에 없는 노드는 무시한다."""
        if node_id not in self.node_zone:
            return  # 알 수 없는 노드(오발행 등)는 버린다
        prev = self._ema.get(node_id)
        if prev is None:
            self._ema[node_id] = float(motion_score)
        else:
            a = self.alpha
            self._ema[node_id] = a * float(motion_score) + (1 - a) * prev
        self._last[node_id] = timestamp

    def _is_stale(self, node_id, now):
        """now가 주어지고 stale_after_s를 넘겼으면 무신호로 본다."""
        if now is None:
            return False
        ts = self._last.get(node_id)
        if ts is None:
            return True
        return (now - ts) > self.stale_after_s

    def zone_states(self, now=None):
        """현재 구역 상태 {zone: ZoneState}. now를 주면 오래된 노드는 무신호 처리."""
        out = {}
        for zone in self.zones:
            nodes = [n for n, z in self.node_zone.items() if z == zone]
            scores = [self._ema[n] for n in nodes
                      if n in self._ema and not self._is_stale(n, now)]
            if not scores:
                out[zone] = ZoneState(active=False, intensity=0.0, reporting=False)
            else:
                intensity = max(scores)   # 같은 구역 다중 노드면 최댓값 채택
                out[zone] = ZoneState(active=intensity >= self.threshold,
                                      intensity=intensity, reporting=True)
        return out

    def active_zones(self, now=None):
        """활성(움직임 감지) 구역 이름 리스트."""
        return [z for z, s in self.zone_states(now).items() if s.active]

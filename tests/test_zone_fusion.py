"""구역 융합기 단위 테스트 (PRD 지정 테스트 대상, 하드웨어 불필요).

경계 케이스: 다중 구역 동시 점등 / 기준선 근처 노이즈 / 일부 노드 무신호 /
3노드↔2노드 구성 전환.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zone_fusion import ZoneFusion  # noqa: E402

ZONES3 = {"node1": "left", "node2": "center", "node3": "right"}
ZONES2 = {"node1": "left", "node3": "right"}


def feed(zf, node, score, n=10, ts=None):
    """평활화를 수렴시키기 위해 같은 점수를 여러 번 흘려넣는다."""
    for _ in range(n):
        zf.update(node, score, timestamp=ts)


class TestZoneFusion(unittest.TestCase):

    def test_single_zone_active(self):
        zf = ZoneFusion(ZONES3, zones=["left", "center", "right"], threshold=0.5)
        feed(zf, "node2", 3.0)
        self.assertEqual(zf.active_zones(), ["center"])

    def test_multi_zone_simultaneous(self):
        # 다중 구역 동시 점등
        zf = ZoneFusion(ZONES3, zones=["left", "center", "right"], threshold=0.5)
        feed(zf, "node1", 2.0)
        feed(zf, "node3", 2.5)
        self.assertEqual(set(zf.active_zones()), {"left", "right"})

    def test_baseline_noise_inactive(self):
        # 기준선 근처 노이즈는 임계값 미만 → 비활성
        zf = ZoneFusion(ZONES3, zones=["left", "center", "right"], threshold=0.5)
        feed(zf, "node1", 0.05)
        feed(zf, "node2", 0.1)
        feed(zf, "node3", 0.0)
        self.assertEqual(zf.active_zones(), [])

    def test_missing_node_no_crash(self):
        # 일부 노드 무신호: node2가 한 번도 보고 안 함 → center는 reporting=False
        zf = ZoneFusion(ZONES3, zones=["left", "center", "right"], threshold=0.5)
        feed(zf, "node1", 2.0)
        feed(zf, "node3", 2.0)
        states = zf.zone_states()
        self.assertFalse(states["center"].reporting)
        self.assertFalse(states["center"].active)
        self.assertTrue(states["left"].active)
        self.assertTrue(states["right"].active)

    def test_two_node_config(self):
        # 2노드 구성 → 좌/우 2구역만
        zf = ZoneFusion(ZONES2, zones=["left", "right"], threshold=0.5)
        feed(zf, "node1", 2.0)
        self.assertEqual(set(zf.zone_states().keys()), {"left", "right"})
        self.assertEqual(zf.active_zones(), ["left"])

    def test_three_to_two_same_logic(self):
        # 3노드↔2노드 구성 전환해도 동일 로직으로 동작
        zf3 = ZoneFusion(ZONES3, zones=["left", "center", "right"], threshold=0.5)
        zf2 = ZoneFusion(ZONES2, zones=["left", "right"], threshold=0.5)
        feed(zf3, "node1", 2.0)
        feed(zf2, "node1", 2.0)
        self.assertEqual(zf3.zone_states()["left"].active,
                         zf2.zone_states()["left"].active)

    def test_unknown_node_ignored(self):
        # 설정에 없는 노드 발행은 무시(크래시 없음)
        zf = ZoneFusion(ZONES3, zones=["left", "center", "right"], threshold=0.5)
        feed(zf, "ghost", 9.0)
        self.assertEqual(zf.active_zones(), [])

    def test_stale_node_drops_out(self):
        # 신호가 끊긴(오래된) 노드는 무신호 처리 (now 기반)
        zf = ZoneFusion(ZONES3, zones=["left", "center", "right"],
                        threshold=0.5, stale_after_s=3.0)
        feed(zf, "node1", 2.0, ts=100.0)
        # 직후엔 활성
        self.assertTrue(zf.zone_states(now=101.0)["left"].active)
        # 5초 뒤엔 무신호
        s = zf.zone_states(now=106.0)["left"]
        self.assertFalse(s.reporting)
        self.assertFalse(s.active)

    def test_max_aggregation_same_zone(self):
        # 같은 구역에 노드 2개면 최댓값 채택
        mapping = {"a": "left", "b": "left"}
        zf = ZoneFusion(mapping, zones=["left"], threshold=0.5)
        feed(zf, "a", 0.1)
        feed(zf, "b", 3.0)
        self.assertTrue(zf.zone_states()["left"].active)
        self.assertAlmostEqual(zf.zone_states()["left"].intensity, 3.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

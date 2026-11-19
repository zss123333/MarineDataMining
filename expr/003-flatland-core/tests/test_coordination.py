import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coordination import Commitment, Coordinator, dependencies
from planning import Plan, collisions, predict
from run import dependency_breaks


class ProtocolTests(unittest.TestCase):
    def test_offmap_departure_is_not_occupancy(self):
        agent = SimpleNamespace(position=None, earliest_departure=3,
                                speed_counter=SimpleNamespace(max_speed=1, distance=0))
        forecast = predict(agent, [((0, 0), 1), ((0, 1), 1)], 0, 0, 8)
        self.assertEqual(forecast[:4], [None]*4)
        self.assertEqual(forecast[4], (0, 0))

    def test_registered_future_clearance_is_protected(self):
        protocol = Coordinator()
        protocol.propose(0, [(0, 0), (0, 1), (0, 2)], 0, 8)
        protocol.register(1, 0, (0, 1), 2, 0)
        proposal = Plan([], 0, 0, [(0, 0), (0, 1), (0, 1)], "wait")
        self.assertEqual(dependency_breaks(protocol, 0, proposal, 0)[0]["consumer"], 1)
        self.assertEqual(protocol.registered[0]["kind"], "future")

    def test_dependency_chain_propagates_but_not_unrelated(self):
        protocol = Coordinator()
        for owner in range(4):
            protocol.propose(owner, [(owner, 0)], 0, 8)
        protocol.register(1, 0, (0, 0), 5, 0)
        protocol.register(2, 1, (1, 0), 6, 0)
        protocol.revoke(0, 1, "fault")
        self.assertEqual(protocol.repairs, {1, 2})

    def test_rejected_version_is_never_reused(self):
        protocol = Coordinator()
        protocol.propose(1, [(0, 0)], 0, 8)
        protocol.propose(0, [(0, 0)], 0, 8)
        protocol.acknowledge(0, 1, 1, 0, False)
        protocol.propose(0, [(0, 0)], 0, 8)
        self.assertEqual(protocol.pending[0][0].version, 2)
        self.assertFalse(protocol.acknowledge(0, 1, 1, 0, True))

    def test_swap_conflict_and_offmap_nonconflict(self):
        self.assertEqual(collisions([(0, 0), (0, 1)], [(0, 1), (0, 0)]), [1])
        self.assertEqual(collisions([None, None], [None, None]), [])

    def test_future_dependency(self):
        peers = {1: Commitment(1, 1, 0, 8, [(2, 2), (1, 2), (1, 1)])}
        found = dependencies(0, [(0, 0), (0, 1), (1, 1)], peers, 0, 8)
        self.assertEqual(found[0]["kind"], "predicted")

    def test_stale_ack_rejected(self):
        protocol = Coordinator()
        protocol.propose(1, [(0, 0), (0, 1)], 0, 8)
        protocol.propose(0, [(1, 0), (0, 1)], 0, 8)
        self.assertFalse(protocol.acknowledge(0, 99, 1, 0, True))
        self.assertNotIn(0, protocol.commitments)
        self.assertTrue(protocol.acknowledge(0, 1, 1, 0, True))
        self.assertIn(0, protocol.commitments)

    def test_revoke_without_consent(self):
        protocol = Coordinator()
        protocol.propose(0, [(0, 0)], 0, 8)
        protocol.revoke(0, 1, "observed malfunction")
        self.assertEqual(protocol.commitments[0].status, "revoked")

    def test_timeout_keeps_old_commitment(self):
        protocol = Coordinator()
        protocol.propose(1, [(0, 0)], 0, 8)
        protocol.propose(0, [(0, 0)], 0, 8)
        protocol.expire(4)
        self.assertNotIn(0, protocol.pending)
        self.assertNotIn(0, protocol.commitments)


if __name__ == "__main__":
    unittest.main()

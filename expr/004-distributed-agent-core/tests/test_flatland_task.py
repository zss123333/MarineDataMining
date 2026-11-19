import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent import Proposal
from flatland_task import FlatlandTask
from flatland.envs.persistence import RailEnvPersister


class FlatlandTests(unittest.TestCase):
    def test_future_route_dependency_without_current_overlap(self):
        from agent import Candidate
        task = FlatlandTask(self.env, 0, public_resources={"0": {(1, 1), (2, 2)},
                            "1": {(2, 2)}, "2": {(9, 9)}})
        choices = (Candidate("keep", {"cells": [(1, 1)]}),)
        self.assertEqual(task.proposal_participants(choices, task.observe()), ("0", "1"))

    def test_resource_dependency_does_not_include_disjoint_peer(self):
        task = FlatlandTask(self.env, 0, public_resources={"0": {(1, 1)}, "1": {(1, 1)}, "2": {(9, 9)}})
        self.assertEqual(task.coordination_peers(None, task.observe()), ("1",))

    def setUp(self):
        source = Path(__file__).resolve().parents[2] / "datasets" / "flatland-core" / "v1" / "Test_00_Level_0.pkl"
        self.env, _ = RailEnvPersister.load_new(str(source))

    def test_local_response_install_and_version_check(self):
        task = FlatlandTask(self.env, 0)
        choices = task.candidates(task.observe())
        proposal = Proposal("test", "0", 0, choices, ("0", "1", "2"))
        response = task.respond(proposal, choices[0], task.observe())
        self.assertTrue(task.valid(response, task.observe()))
        task.install(response)
        self.assertFalse(task.valid(response, task.observe()))
        self.assertIn(task.act(task.observe()), range(5))

    def test_responder_does_not_install_before_commit(self):
        owner = FlatlandTask(self.env, 0)
        peer = FlatlandTask(self.env, 1)
        choices = owner.candidates(owner.observe())
        proposal = Proposal("test", "0", 0, choices, ("0", "1", "2"))
        response = peer.respond(proposal, choices[0], peer.observe())
        self.assertIsNone(peer.plan)
        self.assertEqual(peer.version, 0)
        self.assertIn("cells", response.public)
        self.assertNotIn("plan", response.public)

    def test_revoke_stops_execution(self):
        task = FlatlandTask(self.env, 0)
        choices = task.candidates(task.observe())
        proposal = Proposal("test", "0", 0, choices, ("0", "1", "2"))
        task.install(task.respond(proposal, choices[0], task.observe()))
        task.revoke(task.observe())
        self.assertEqual(task.act(task.observe()), 4)
        self.assertTrue(task.dirty)


if __name__ == "__main__":
    unittest.main()

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import agent
from demo import build, run_round


class AdaptiveCoreTests(unittest.TestCase):
    def test_conflict_retains_revision_for_next_observation(self):
        agents, mailbox = build()
        for member in agents:
            member.task.compatible = lambda candidate, reports: False
        run_round(agents, mailbox, 0)
        self.assertIsNotNone(agents[0].pending_revision)
        for member in agents:
            member.task.compatible = lambda candidate, reports: True
        for step in (1, 2, 3):
            run_round(agents, mailbox, step)
        self.assertGreater(agents[0].task.version, 0)

    def test_internal_update_has_no_messages(self):
        agents, mailbox = build()
        for member in agents:
            member.task.local_revision = lambda candidates, observation: agent.Response(True, 0, {}, {"version": observation["version"], "action": "internal"})
            member.task.external_conditions_unchanged = lambda response, observation: True
        self.assertEqual(run_round(agents, mailbox, 0), dict.fromkeys(("A", "B", "C"), "internal"))
        self.assertEqual(mailbox.messages, [])

    def test_changed_external_condition_cannot_use_local_branch(self):
        agents, mailbox = build()
        agents[0].task.local_revision = lambda candidates, observation: agent.Response(True, 0, {}, {"version": 0, "action": "internal"})
        agents[0].task.external_conditions_unchanged = lambda response, observation: False
        run_round(agents, mailbox, 0)
        self.assertTrue(any(message.kind == "propose" for message in mailbox.messages))

    def test_feedback_boundary_blocks_until_replanned(self):
        agents, mailbox = build()
        for member in agents:
            member.task.feedback_boundary = lambda response, observation: 1
            member.task.safe_action = lambda observation: "stop"
        run_round(agents, mailbox, 0)
        for member in agents:
            member.task.needs_revision = lambda observation: False
            member.task.compatible = lambda candidate, reports: False
        self.assertEqual(run_round(agents, mailbox, 1), dict.fromkeys(("A", "B", "C"), "stop"))

    def test_act_time_emergency_notifies_peers(self):
        agents, mailbox = build()
        agents[0].task.broken = True
        self.assertEqual(agents[0].act(), "stop")
        self.assertEqual({message.receiver for message in mailbox.messages}, {"B", "C"})

    def test_expired_commitment_prevents_execution(self):
        agents, mailbox = build()
        member = agents[0]
        member.task.safe_action = lambda observation: "stop"
        member.ledger.register_commitment(agent.Commitment("route", "A", 1, "clear", 0, 1))
        member.active_round = 1
        self.assertEqual(member.act(), "stop")

    def test_revoke_uses_registered_consumers_only(self):
        agents, mailbox = build()
        member = agents[0]
        member.ledger.register_commitment(agent.Commitment("route", "A", 1, "clear", 0, 10))
        member.ledger.register_dependency(agent.Dependency("future", "B", "A", "route", 1, 5, 9))
        member.task.broken = True
        member.act()
        self.assertEqual({message.receiver for message in mailbox.messages}, {"B"})

    def test_delta_without_matching_base_aborts(self):
        agents, mailbox = build()
        owner = agents[0]
        owner.step(0)
        key = next(iter(owner.proposals))
        owner.think(agent.Message("B", "A", "respond_delta", key,
                                 {"base": 99, "version": 100, "changed": {}, "removed": []}))
        self.assertTrue(any(event.get("event") == "delta_base_mismatch" for event in owner.trace))
        self.assertTrue(any(message.kind == "abort" for message in mailbox.messages))

    def test_constraint_round_regenerates_responses(self):
        agents, mailbox = build()
        for member in agents:
            original = member.task.respond
            member.task.respond = lambda proposal, candidate, observation, original=original: agent.Response(proposal.attempt > 0, 0, {}, original(proposal, candidate, observation).private_plan)
            member.task.negotiation_constraints = lambda proposal, reports, reason: {"allow_adjustment": True}
        run_round(agents, mailbox, 0)
        proposals = [message.payload for message in mailbox.messages if message.kind == "propose"]
        self.assertEqual({proposal.attempt for proposal in proposals}, {0, 1})
        self.assertTrue(all(member.task.version == 1 for member in agents))

    def test_negotiation_rounds_are_bounded(self):
        agents, mailbox = build()
        for member in agents:
            member.task.compatible = lambda candidate, reports: False
            member.task.negotiation_constraints = lambda proposal, reports, reason: {"retry": proposal.attempt}
        run_round(agents, mailbox, 0)
        attempts = {message.payload.attempt for message in mailbox.messages if message.kind == "propose"}
        self.assertEqual(attempts, {0, 1, 2})

    def test_cache_reuses_only_valid_evaluations(self):
        agents, mailbox = build()
        member = agents[1]
        member.task.evaluation_key = lambda proposal, candidate, observation: observation["version"]
        candidates = member.task.candidates(member.task.observe())
        for index in range(2):
            proposal = agent.Proposal(str(index), "A", 0, candidates, ("A", "B", "C"))
            member.think(agent.Message("A", "B", "propose", str(index), proposal))
        self.assertEqual(sum(event.get("event") == "evaluation_reused" for event in member.trace), 4)

    def test_repair_options_participate_in_selection(self):
        agents, mailbox = build()
        for member in agents:
            member.task.repair_options = lambda proposal, candidate, observation, primary: [agent.Response(True, -100, primary.public, {"version": observation["version"], "action": "repair"})]
        self.assertEqual(run_round(agents, mailbox, 0), dict.fromkeys(("A", "B", "C"), "repair"))

    def test_delta_messages_reconstruct_and_commit(self):
        agents, mailbox = build()
        for member in agents:
            member.delta_messages = True
            original = member.task.respond
            member.task.respond = lambda proposal, candidate, observation, original=original: agent.Response(False, 0, {"large": "x"*4000}, original(proposal, candidate, observation).private_plan)
        run_round(agents, mailbox, 0)
        run_round(agents, mailbox, 3)
        self.assertTrue(any(message.kind == "respond_delta" for message in mailbox.messages))
        self.assertFalse(any(event.get("event") == "delta_base_mismatch" for member in agents for event in member.trace))

    def test_dependency_lifecycle_and_future_window(self):
        ledger = agent.Ledger()
        ledger.register_commitment(agent.Commitment("route", "A", 1, "clear", 0, 10))
        ledger.register_dependency(agent.Dependency("future", "B", "A", "route", 1, 5, 9))
        self.assertEqual(ledger.peers("A"), {"B"})
        ledger.release("future")
        self.assertEqual(ledger.peers("A"), set())
        ledger.register_dependency(agent.Dependency("next", "C", "A", "route", 1, 7, 9))
        ledger.register_commitment(agent.Commitment("route", "A", 2, "clear", 0, 12))
        self.assertEqual(ledger.dependencies["next"].status, "invalidated")
        ledger.advance(12)
        self.assertEqual(ledger.commitments["route"].status, "expired")
        with self.assertRaises(ValueError):
            ledger.register_dependency(agent.Dependency("bad", "B", "A", "route", 1, 0, 20))


if __name__ == "__main__":
    unittest.main()

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent import Agent, Message, Response
from demo import ExampleTask, Mailbox, build, run_round


class DistributedTests(unittest.TestCase):
    def test_conflicting_primary_responses_use_local_alternative(self):
        agents, mailbox = build()
        for agent in agents:
            identity = agent.identity
            def menus(proposal, candidate, observation, primary, identity=identity):
                primary.public["slot"] = 0 if identity in ("B", "C") else 2
                if identity == "C":
                    return [primary, Response(True, primary.delta_cost+1, {"slot": 1}, primary.private_plan)]
                return [primary]
            agent.task.response_options = menus
            agent.task.compatible = lambda candidate, reports: len({report["public"]["slot"] for report in reports.values()}) == 3
        run_round(agents, mailbox, 0)
        found = [event for event in agents[0].trace if event.get("event") == "combination_found"]
        self.assertTrue(found)
        self.assertTrue(all(event["selection"]["C"] == 1 for event in found))
        self.assertTrue(all(event["combinations_checked"] > 1 for event in found))

    def test_cannot_execute_while_prepared(self):
        agents, _ = build()
        agents[0].locked = "transaction"
        with self.assertRaises(RuntimeError):
            agents[0].act()

    def test_dependency_cycle_does_not_expand_forever(self):
        agents, mailbox = build()
        for agent in agents:
            agent.task.coordination_peers = lambda proposal, observation: ("A", "B", "C")
        run_round(agents, mailbox, 0)
        self.assertEqual(len({message.proposal for message in mailbox.messages}), 1)

    def test_cross_group_dependency_expands_without_global_broadcast(self):
        members = ("A", "B", "C", "D", "E", "F")
        mailbox = Mailbox()
        agents = []
        for identity in members:
            task = ExampleTask(identity if identity in ["A", "B", "C"] else "C")
            task.needs_revision = lambda observation: False
            dependencies = {"B": ("D",), "D": ("E",)}.get(identity, ())
            task.coordination_peers = lambda proposal, observation, peers=dependencies: peers
            group = ("A", "B", "C") if identity in ("A", "B", "C") else ("D", "E", "F")
            agents.append(Agent(identity, members, task, mailbox, task_group=group))
        agents[0].task.needs_revision = lambda observation: True
        run_round(agents, mailbox, 0)
        commits = [message for message in mailbox.messages if message.kind == "commit"]
        self.assertEqual({message.receiver for message in commits}, {"A", "B", "C", "D", "E"})
        self.assertTrue(all(message.receiver != "F" for message in mailbox.messages))
        proposals = [message.payload for message in mailbox.messages if message.kind == "propose"]
        self.assertGreater(len({proposal.key for proposal in proposals}), 1)
        self.assertTrue(all(agent.locked is None for agent in agents))

    def test_prepare_lock_rejects_overlapping_transaction(self):
        agents, mailbox = build()
        agent = agents[1]
        agents[0].step(0)
        proposal_message = next(message for message in mailbox.messages if message.receiver == "B")
        agent.think(proposal_message)
        agent.locked = "other-group-transaction"
        agent.think(Message("A", "B", "prepare", proposal_message.proposal, "joint"))
        self.assertFalse(mailbox.messages[-1].payload)

    def test_task_group_does_not_message_outsiders(self):
        original, mailbox = build()
        members = ("A", "B", "C", "D", "E")
        group = ("A", "B", "C")
        agents = [Agent(agent.identity, members, agent.task, mailbox, task_group=group) for agent in original]
        result = run_round(agents, mailbox, 0)
        self.assertEqual(result, dict.fromkeys(group, "joint"))
        self.assertTrue(all(message.receiver in group for message in mailbox.messages))

    def test_three_agents_choose_reported_team_cost(self):
        agents, mailbox = build()
        self.assertEqual(run_round(agents, mailbox, 0), dict.fromkeys(["A", "B", "C"], "joint"))
        self.assertTrue(all(agent.task.version == 1 for agent in agents))

    def test_private_plans_never_sent(self):
        agents, mailbox = build()
        run_round(agents, mailbox, 0)
        replies = [message for message in mailbox.messages if message.kind == "respond"]
        self.assertEqual(len(replies), 3)
        self.assertTrue(all("private_plan" not in str(message.payload) for message in replies))

    def test_revision_invalidates_preparation(self):
        agents, mailbox = build()
        result = run_round(agents, mailbox, 0, lambda: setattr(agents[1].task, "version", 9))
        self.assertEqual(result, dict.fromkeys(["A", "B", "C"], "keep"))
        self.assertTrue(all(agent.trace[-1]["decision"] == "abort" for agent in agents))

    def test_proposal_owner_rotates(self):
        agents, mailbox = build()
        for round in range(3):
            run_round(agents, mailbox, round)
        owners = {message.sender for message in mailbox.messages if message.kind == "propose"}
        self.assertEqual(owners, {"A", "B", "C"})

    def test_replayed_commit_cannot_install_twice(self):
        agents, mailbox = build()
        run_round(agents, mailbox, 0)
        commit = next(message for message in mailbox.messages if message.kind == "commit")
        target = next(agent for agent in agents if agent.identity == commit.receiver)
        target.think(commit)
        self.assertEqual(target.task.version, 1)

    def test_requires_three_members(self):
        agents, mailbox = build()
        with self.assertRaises(ValueError):
            Agent("A", ("A", "B"), agents[0].task, mailbox)

    def test_emergency_is_announced_without_approval(self):
        agents, mailbox = build()
        agents[1].task.broken = True
        result = run_round(agents, mailbox, 0)
        self.assertEqual(result["B"], "stop")
        self.assertIn("B", agents[2].task.changed)


if __name__ == "__main__":
    unittest.main()

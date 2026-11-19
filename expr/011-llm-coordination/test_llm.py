import unittest

from run import Agent, Candidate, Mailbox, ResourceTask, run_round


class ScriptedModel:
    def __init__(self):
        self.calls = []

    def decide(self, identity, stage, context):
        self.calls.append((identity, stage, context))
        if stage == "revise":
            return {"request": "coordinate"}
        forbidden = context["forbidden_slots"]
        return {"slot": next(slot for slot in range(10) if slot not in forbidden)}


class ModelIntegrationTest(unittest.TestCase):
    def test_malformed_model_output_is_retried(self):
        import json
        from agent import Proposal
        class FlakyModel(ScriptedModel):
            def decide(self, identity, stage, context):
                if not self.calls:
                    self.calls.append((identity, stage, context))
                    raise json.JSONDecodeError("truncated", "{", 1)
                return super().decide(identity, stage, context)
        model = FlakyModel()
        task = ResourceTask("0", 3, False, 0)
        member = Agent("0", ("0", "1", "2"), task, Mailbox(), decision_model=model)
        candidate = Candidate("reservation", {})
        proposal = Proposal("test", "0", 0, (candidate,), ("0", "1", "2"))
        response = member.generate_response(proposal, candidate, task.observe())
        self.assertTrue(response.feasible)
        self.assertEqual(len(model.calls), 2)

    def test_all_members_generate_and_revise_own_responses(self):
        model = ScriptedModel()
        mailbox = Mailbox()
        members = ("0", "1", "2")
        agents = [Agent(identity, members, ResourceTask(identity, 3, False, 0), mailbox,
                        max_negotiation_rounds=8, decision_model=model) for identity in members]
        run_round(agents, mailbox, 0)
        self.assertEqual([agent.task.plan.segments["shared"] for agent in agents], [0, 1, 2])
        self.assertEqual({identity for identity, stage, _ in model.calls if stage == "respond"}, set(members))
        self.assertTrue(any(context["coordination_feedback"] for _, stage, context in model.calls if stage == "respond"))
        calls = len(model.calls)
        run_round(agents, mailbox, 1)
        self.assertEqual(len(model.calls), calls)
        self.assertTrue(all(agent.task.plan.versions["other"] == 0 for agent in agents))

    def test_invalid_slot_is_not_installed(self):
        task = ResourceTask("0", 3, False, 0)
        with self.assertRaises(ValueError):
            task.response_from_decision({"slot": -1}, type("Proposal", (), {"constraints": None})(),
                                        Candidate("reservation", {}), task.observe())
        self.assertEqual(task.installs, 0)


if __name__ == "__main__":
    unittest.main()

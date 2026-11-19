import unittest

from run import Agent, DynamicTask, Mailbox, run_round


class Model:
    def decide(self, identity, stage, context):
        if stage == "revise":
            return {"request": "coordinate"}
        return {"slot": context["output_schema"]["properties"]["slot"]["enum"][0]}


class DynamicTest(unittest.TestCase):
    def test_prepared_slot_invalid_after_release_change(self):
        from run import resource
        task = DynamicTask("0", 3, 0, True)
        proposal = type("Proposal", (), {"constraints": None})()
        response = task.response_from_decision({"slot": 1}, proposal, resource.Candidate("r", {}), task.observe())
        self.assertTrue(task.valid(response, task.observe()))
        task.release = 12
        self.assertFalse(task.valid(response, task.observe()))

    def test_recoordinate_after_window_change(self):
        members = ("0", "1", "2", "3")
        mailbox = Mailbox()
        tasks = [DynamicTask(identity, 3, 0, True) for identity in members]
        agents = [Agent(identity, members, task, mailbox, max_negotiation_rounds=8, decision_model=Model())
                  for identity, task in zip(members, tasks)]
        run_round(agents, mailbox, 0)
        self.assertEqual([task.installs for task in tasks[:3]], [1, 1, 1])
        for task in tasks:
            task.release = 12
            task.required_installs = 2
        agents[0].emergency(tasks[0].observe())
        run_round(agents, mailbox, 4)
        self.assertEqual([task.installs for task in tasks[:3]], [2, 2, 2])
        self.assertTrue(all(task.plan.segments["shared"] >= 12 for task in tasks[:3]))
        self.assertTrue(all(task.plan.versions["other"] == 0 for task in tasks))
        self.assertFalse(any(message.receiver == "3" for message in mailbox.messages))


if __name__ == "__main__":
    unittest.main()

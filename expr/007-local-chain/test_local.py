import copy
import unittest
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

spec = spec_from_file_location("local_chain_demo", Path(__file__).with_name("demo.py"))
local = module_from_spec(spec)
spec.loader.exec_module(local)


class LocalTests(unittest.TestCase):
    def test_chain_preserves_unaffected_segments_and_excludes_outsider(self):
        agents, mailbox = local.build_local()
        before = [copy.deepcopy(member.task.plan.segments["independent"]) for member in agents]
        local.run_round(agents, mailbox, 0)
        self.assertEqual({message.receiver for message in mailbox.messages}, {"A", "B", "C", "D"})
        for index, member in enumerate(agents):
            self.assertEqual(member.task.plan.segments["independent"], before[index])
            self.assertEqual(member.task.plan.versions["independent"], 0)
            self.assertEqual(member.task.applied, 0 if member.identity == "E" else 1)
        self.assertEqual(agents[-1].task.generations, 0)
        self.assertNotIn("private work", str([message.payload for message in mailbox.messages]))

    def test_unrelated_edit_does_not_invalidate_patch(self):
        plan = local.SegmentedPlan({"shared": 1, "other": 2})
        patch = local.PlanPatch({"shared": 0}, {"shared": 3})
        plan.apply(local.PlanPatch({"other": 0}, {"other": 4}))
        self.assertTrue(plan.valid(patch))
        plan.apply(patch)
        self.assertEqual(plan.segments, {"shared": 3, "other": 4})

    def test_stale_relevant_read_rejects_patch(self):
        plan = local.SegmentedPlan({"shared": 1, "dependency": 2})
        patch = local.PlanPatch({"shared": 0, "dependency": 0}, {"shared": 3})
        plan.apply(local.PlanPatch({"dependency": 0}, {"dependency": 4}))
        self.assertFalse(plan.valid(patch))
        with self.assertRaises(ValueError):
            plan.apply(patch)


if __name__ == "__main__":
    unittest.main()
